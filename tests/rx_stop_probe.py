"""Exercise real Stop -> host StopReceive -> StopPipe and RX return functions.

The target-stop shim injects a final enqueue before declaring the producer
quiescent, as cancel-and-wait permits. No real WDF threads or USB are exercised.
Missing drainage, premature return, duplicate return and stale Stop/Start state
are the production breaks this test is intended to catch.
"""
from pathlib import Path
import subprocess
import sys
import tempfile

import ntb_review_probe as ntb
from rx_completion_probe import function_from_source, root, rx_struct, shim as rx_shim

functions = '\n'.join([
    function_from_source(root / 'common/buffers.cpp', 'NTSTATUS\nRxBufferQueueEnqueueBuffer('),
    function_from_source(root / 'common/buffers.cpp', 'NTSTATUS\nRxBufferQueueDequeueBuffer('),
    function_from_source(root / 'common/buffers.cpp', 'void\nRxBufferQueueReturnBuffer('),
    function_from_source(root / 'host/device.cpp', 'NTSTATUS\nStartPipe('),
    function_from_source(root / 'host/device.cpp', 'void\nStopPipe('),
    function_from_source(root / 'host/device.cpp', 'void\nUsbNcmHostDevice::StartReceive('),
    function_from_source(root / 'host/device.cpp', 'void\nUsbNcmHostDevice::StopReceive('),
    function_from_source(root / 'adapter/rxqueue.cpp', 'void\nNcmRxQueue::Start('),
    function_from_source(root / 'adapter/rxqueue.cpp', 'void\nNcmRxQueue::Stop('),
])
shim = r'''
#include <deque>
#include <utility>
using LONG=long; using WDFDEVICE=void*; using WDFIOTARGET=void*;
constexpr int STATUS_UNSUCCESSFUL=-5;
constexpr int WdfIoTargetCancelSentIo=1;
#define PAGED_CODE() ((void)0)
static LONG InterlockedExchange(LONG* p,LONG value) { return std::exchange(*p,value); }
struct Queue {
  std::vector<std::unique_ptr<RX_BUFFER>> all;
  std::deque<RX_BUFFER*> ready;
};
static bool targetStopped=false, duringStop=false;
static int prematureReturns=0;
static NTSTATUS DMF_BufferQueue_Fetch(DMFMODULE q,PVOID* out,PVOID*) {
  auto* queue=static_cast<Queue*>(q); auto b=std::make_unique<RX_BUFFER>();
  *out=b.get(); queue->all.push_back(std::move(b)); return STATUS_SUCCESS;
}
static void DMF_BufferQueue_Enqueue(DMFMODULE q,RX_BUFFER* b) { static_cast<Queue*>(q)->ready.push_back(b); }
static NTSTATUS DMF_BufferQueue_Dequeue(DMFMODULE q,PVOID* out,PVOID*) {
  auto* queue=static_cast<Queue*>(q);
  if(queue->ready.empty()) { *out=nullptr; return STATUS_UNSUCCESSFUL; }
  *out=queue->ready.front(); queue->ready.pop_front(); return STATUS_SUCCESS;
}
static void DMF_BufferQueue_Reuse(DMFMODULE,RX_BUFFER*) {
  if(duringStop && !targetStopped) ++prematureReturns;
}
static void DMF_ContinuousRequestTarget_BufferPut(DMFMODULE,PUCHAR) {}
NTSTATUS RxBufferQueueEnqueueBuffer(RX_BUFFER_QUEUE,PUCHAR,size_t,WDFMEMORY,WDFOBJECT);
NTSTATUS RxBufferQueueDequeueBuffer(RX_BUFFER_QUEUE,RX_BUFFER**);
void RxBufferQueueReturnBuffer(RX_BUFFER_QUEUE,RX_BUFFER*);
struct Pipe { Queue* queue; Memory* finalCompletion=nullptr; };
static WDFIOTARGET WdfUsbTargetPipeGetIoTarget(WDFUSBPIPE p) { return p; }
static NTSTATUS WdfIoTargetStart(WDFIOTARGET) { targetStopped=false; return STATUS_SUCCESS; }
static void WdfIoTargetStop(WDFIOTARGET h,int action) {
  assert(action==WdfIoTargetCancelSentIo); duringStop=true;
  auto* pipe=static_cast<Pipe*>(h);
  if(pipe->finalCompletion) {
    auto* memory=pipe->finalCompletion; pipe->finalCompletion=nullptr;
    assert(RxBufferQueueEnqueueBuffer(pipe->queue,nullptr,64,memory,nullptr)==STATUS_SUCCESS);
  }
  targetStopped=true;
}
struct UsbNcmHostDevice {
  WDFUSBPIPE m_DataBulkInPipe;
  static void StartReceive(WDFDEVICE);
  static void StopReceive(WDFDEVICE);
};
static UsbNcmHostDevice* NcmGetHostDeviceFromHandle(WDFDEVICE h) { return static_cast<UsbNcmHostDevice*>(h); }
struct Callbacks { void (*EvtUsbNcmStartReceive)(WDFDEVICE); void (*EvtUsbNcmStopReceive)(WDFDEVICE); };
struct NcmAdapter {
  Callbacks* m_UsbNcmDeviceCallbacks; UsbNcmHostDevice* host;
  WDFDEVICE GetWdfDevice() { return host; }
};
struct NcmRxQueue {
  NcmAdapter* m_NcmAdapter;
  RX_BUFFER_QUEUE m_RxBufferQueue;
  RX_BUFFER* m_RxBufferInProcessing=nullptr;
  LONG m_NotificationEnabled=1;
  void Start(); void Stop();
};
'''
main = r'''
int main() {
  int failures=0;
  for(bool populate:{false,true}) {
    Queue queue; Pipe pipe{&queue}; UsbNcmHostDevice host{&pipe};
    Callbacks callbacks{UsbNcmHostDevice::StartReceive,UsbNcmHostDevice::StopReceive};
    NcmAdapter adapter{&callbacks,&host}; NcmRxQueue rx{&adapter,&queue};
    Memory buffers[4]; for(auto& b:buffers) b.bytes.resize(128);
    heldReferences=0; prematureReturns=0; duringStop=false; targetStopped=false;
    if(populate) {
      for(int i=0;i<3;++i) assert(RxBufferQueueEnqueueBuffer(&queue,nullptr,64,&buffers[i],nullptr)==STATUS_SUCCESS);
      assert(RxBufferQueueDequeueBuffer(&queue,&rx.m_RxBufferInProcessing)==STATUS_SUCCESS);
      pipe.finalCompletion=&buffers[3];
    }
    rx.Stop();
    bool clean=heldReferences==0 && queue.ready.empty() && rx.m_RxBufferInProcessing==nullptr &&
      prematureReturns==0 && rx.m_NotificationEnabled==0 && targetStopped;
    std::printf("%s Stop: refs=%d queued=%zu processing=%d premature-returns=%d notification=%ld %s\n",
      populate?"partial+queued+final-completion":"empty",heldReferences,queue.ready.size(),
      rx.m_RxBufferInProcessing!=nullptr,prematureReturns,rx.m_NotificationEnabled,clean?"PASS":"FAIL");
    failures+=!clean;
    // Baseline Stop lacks cleanup. Explicit test-owned cleanup avoids carrying
    // its failure into the subsequent idempotence/restart observations.
    if(rx.m_RxBufferInProcessing) {
      RxBufferQueueReturnBuffer(&queue,rx.m_RxBufferInProcessing); rx.m_RxBufferInProcessing=nullptr;
    }
    RX_BUFFER* b=nullptr;
    while(RxBufferQueueDequeueBuffer(&queue,&b)==STATUS_SUCCESS) RxBufferQueueReturnBuffer(&queue,b);
    rx.m_NotificationEnabled=0;
    rx.Stop(); assert(heldReferences==0 && queue.ready.empty());
    duringStop=false; rx.Start(); assert(!targetStopped);
    assert(RxBufferQueueEnqueueBuffer(&queue,nullptr,64,&buffers[0],nullptr)==STATUS_SUCCESS);
    rx.m_NotificationEnabled=1; rx.Stop();
    clean=heldReferences==0 && queue.ready.empty() && prematureReturns==0 && rx.m_NotificationEnabled==0;
    failures+=!clean;
    std::printf("Stop-Start-Stop reuse %s\n",clean?"PASS":"FAIL");
    while(RxBufferQueueDequeueBuffer(&queue,&b)==STATUS_SUCCESS) RxBufferQueueReturnBuffer(&queue,b);
    assert(heldReferences==0);
  }
  std::printf("RX Stop: %d contract failures\n",failures);
  return failures!=0;
}
'''


def run_probe():
    with tempfile.TemporaryDirectory(prefix='sideline-ncm-stop-') as tmp:
        cpp = Path(tmp) / 'probe.cpp'
        cpp.write_text(ntb.shim + rx_shim + rx_struct + shim + functions + main)
        binary = Path(tmp) / 'probe'
        subprocess.run(['clang++', '-std=c++17', '-fsanitize=address,undefined',
                        '-g', str(cpp), '-o', str(binary)], check=True)
        return subprocess.run([str(binary)]).returncode


if __name__ == '__main__':
    sys.exit(run_probe())
