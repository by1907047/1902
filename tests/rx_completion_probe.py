"""Exercise actual completion -> adapter -> enqueue -> NTB parser code.

Only WDF/DMF handles and queue operations are shimmed. This tests logical
transfer extent, not real WDF scheduling, driver loading or USB hardware.
An exit of 1 means the expected pre-load safety contract is violated.
"""
from pathlib import Path
import subprocess
import sys
import tempfile

import ntb_review_probe as ntb


def function_from_source(path, signature):
    source = path.read_text()
    start = source.index(signature)
    brace = source.index('{', start)
    depth = 1
    end = brace + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


root = ntb.root
buffer_header = (root / 'inc/buffers.h').read_text()
rx_struct = buffer_header[buffer_header.index('struct RX_BUFFER'):buffer_header.index('struct TX_BUFFER_REQUEST')]
functions = '\n'.join([
    function_from_source(root / 'common/buffers.cpp', 'NTSTATUS\nRxBufferQueueEnqueueBuffer('),
    function_from_source(root / 'common/buffers.cpp', 'void\nRxBufferQueueDiscardBuffer('),
    function_from_source(root / 'adapter/adapter.cpp', 'inline\nvoid\nNcmAdapter::NotifyReceive('),
    function_from_source(root / 'host/device.cpp', 'VOID\nUsbNcmHostDevice::DataBulkInPipeReadCompletetionRoutine('),
    function_from_source(root / 'common/buffers.cpp', 'void\nRxBufferQueueReturnBuffer('),
])
shim = r'''
#include <unordered_map>
#define _In_reads_opt_(x)
#define _In_opt_
#define _Use_decl_annotations_
#define NT_SUCCESS(s) ((s)>=0)
using VOID=void; using PVOID=void*; using WDFUSBPIPE=void*;
using WDFCONTEXT=void*; using WDFOBJECT=void*; using HANDLE=void*;
using DMFMODULE=void*; using RX_BUFFER_QUEUE=void*; using NETADAPTER=void*;
constexpr auto WDF_NO_HANDLE=nullptr;
constexpr int STATUS_INSUFFICIENT_RESOURCES=-4;
static int heldReferences=0;
static std::unordered_map<WDFMEMORY,int> objectReferences;
static void WdfObjectReference(WDFMEMORY m) { ++objectReferences[m]; ++heldReferences; }
static void WdfObjectDereference(WDFMEMORY m) {
  assert(objectReferences[m]>0); --objectReferences[m]; --heldReferences;
}
'''
queue_shim = r'''
struct Queue { RX_BUFFER buffer; bool enqueued=false; int notifications=0; int fetchStatus=0; int fetchCalls=0; };
static NTSTATUS DMF_BufferQueue_Fetch(DMFMODULE q, PVOID* out, PVOID*) {
  auto* queue=static_cast<Queue*>(q); assert(!queue->enqueued);
  ++queue->fetchCalls;
  if(queue->fetchStatus!=STATUS_SUCCESS) return queue->fetchStatus;
  *out=&queue->buffer; return STATUS_SUCCESS;
}
static void DMF_BufferQueue_Enqueue(DMFMODULE q, RX_BUFFER*) {
  static_cast<Queue*>(q)->enqueued=true;
}
static void DMF_BufferQueue_Reuse(DMFMODULE q, RX_BUFFER*) {
  static_cast<Queue*>(q)->enqueued=false;
}
static int bufferPuts=0; static DMFMODULE lastPutModule=nullptr; static PUCHAR lastPutBuffer=nullptr;
static void DMF_ContinuousRequestTarget_BufferPut(DMFMODULE m, PUCHAR b) {
  ++bufferPuts; lastPutModule=m; lastPutBuffer=b;
}
NTSTATUS RxBufferQueueEnqueueBuffer(RX_BUFFER_QUEUE, PUCHAR, size_t, WDFMEMORY, WDFOBJECT);
struct RxQueue {
  RX_BUFFER_QUEUE m_RxBufferQueue;
  int drops=0;
  void NotifyReceive() { ++static_cast<Queue*>(m_RxBufferQueue)->notifications; }
  void CountDroppedNtb(NTSTATUS) { ++drops; }
};
struct NcmAdapter {
  RxQueue* m_RxQueue;
  static void NotifyReceive(NETADAPTER, PUCHAR, size_t, WDFMEMORY, WDFOBJECT);
};
static NcmAdapter* NcmGetAdapterFromHandle(NETADAPTER h) { return static_cast<NcmAdapter*>(h); }
struct AdapterCallbacks {
  void (*EvtUsbNcmAdapterNotifyReceive)(NETADAPTER, PUCHAR, size_t, WDFMEMORY, WDFOBJECT);
};
struct UsbNcmHostDevice {
  UINT32 m_HostSelectedNtbInMaxSize;
  AdapterCallbacks* m_NcmAdapterCallbacks;
  NETADAPTER m_NetAdapter;
  static VOID DataBulkInPipeReadCompletetionRoutine(WDFUSBPIPE, WDFMEMORY, size_t, WDFCONTEXT);
};
'''
main = r'''
using Test16=NcmTransferBlock<NcmTransferHeader16,NcmDatagramPointerTable16,NcmDatagramPointer16,
                            UINT16,0x484d434e,0x304d434e,0x314d434e>;
using Test32=NcmTransferBlock<NcmTransferHeader32,NcmDatagramPointerTable32,NcmDatagramPointer32,
                            UINT32,0x686d636e,0x306d636e,0x316d636e>;
template<class Ntb>
static int Check(bool use32) {
  Ntb ntb; assert(ntb.InitializeNtb(nullptr,1,4,4,0,use32)==STATUS_SUCCESS);
  // A previous full valid transfer stays in the tail of a larger allocation.
  // Completion prefixes are the logical newly received lengths.
  Memory memory; memory.bytes.resize(128,0);
  NcmPacketIterator packet; packet.packet.resize(14,0x55);
  assert(ntb.ReInitializeBuffer(memory.bytes.data(),memory.bytes.size(),NTB_TX)==STATUS_SUCCESS);
  assert(ntb.CopyNextDatagram(&packet)==STATUS_SUCCESS);
  size_t fullLength=0; ntb.SetNdp(&fullLength);
  assert(fullLength==(use32?64u:44u));
  Queue queue; RxQueue rxQueue{&queue}; NcmAdapter adapter{&rxQueue};
  AdapterCallbacks callbacks{NcmAdapter::NotifyReceive};
  UsbNcmHostDevice host{128,&callbacks,&adapter};
  size_t wrongExtent=0, unsafeFrames=0, fullFrames=0, directRejects=0;
  for(size_t received=0;received<=fullLength;++received) {
    // A control using the real logical extent proves the same parser rejects
    // these prefixes when its caller does not substitute allocation capacity.
    auto direct=ntb.ReInitializeBuffer(memory.bytes.data(),received,NTB_RX);
    if(received<fullLength) {
      assert(direct==STATUS_BAD_DATA);
      ++directRejects;
    }
    else assert(direct==STATUS_SUCCESS);
    UsbNcmHostDevice::DataBulkInPipeReadCompletetionRoutine(nullptr,&memory,received,&host);
    if(!queue.enqueued) {
      if(received==fullLength) return 2;
      continue;
    }
    assert(heldReferences==1);
    if(queue.buffer.BufferSize!=received) ++wrongExtent;
    auto status=ntb.ReInitializeBuffer(queue.buffer.Buffer,queue.buffer.BufferSize,NTB_RX);
    PUCHAR data=nullptr; size_t size=0;
    if(status==STATUS_SUCCESS) status=ntb.GetNextDatagram(&data,&size);
    if(status==STATUS_SUCCESS) {
      if(received<fullLength) ++unsafeFrames;
      else {
        assert(size==14 && std::memcmp(data,packet.packet.data(),14)==0);
        ++fullFrames;
      }
    }
    RxBufferQueueReturnBuffer(&queue,&queue.buffer);
    assert(heldReferences==0 && !queue.enqueued);
  }
  std::printf("NTB%s: allocation=128 full-transfer=%zu short-prefixes=%zu wrong-extent=%zu tail-dependent-frames=%zu valid-full-frames=%zu direct-length-control-rejects=%zu\n",
              use32?"32":"16",fullLength,fullLength,wrongExtent,unsafeFrames,fullFrames,directRejects);
  return wrongExtent==0 && unsafeFrames==0 && fullFrames==1 ? 0 : 1;
}
static int InvalidBorrowedExtent() {
  Memory memory; memory.bytes.resize(128);
  size_t failures=0;
  struct Case { size_t length; WDFMEMORY memory; WDFOBJECT context; };
  for(auto test : {Case{0,&memory,nullptr},Case{129,&memory,nullptr},
                   Case{64,nullptr,nullptr},Case{64,&memory,reinterpret_cast<void*>(uintptr_t(1))}}) {
    Queue queue;
    const auto status=RxBufferQueueEnqueueBuffer(&queue,nullptr,test.length,test.memory,test.context);
    const bool rejected=status==STATUS_BAD_DATA && !queue.enqueued && heldReferences==0;
    if(!rejected) ++failures;
    if(queue.enqueued) RxBufferQueueReturnBuffer(&queue,&queue.buffer);
    assert(heldReferences==0);
  }
  std::printf("borrowed-memory zero/over-capacity/missing-handle/mixed-owner rejection failures=%zu\n",failures);
  return failures!=0;
}
static int FailedEnqueueDoesNotNotify() {
  Memory memory; memory.bytes.resize(128);
  Queue queue; queue.fetchStatus=STATUS_INSUFFICIENT_RESOURCES;
  RxQueue rxQueue{&queue}; NcmAdapter adapter{&rxQueue};
  AdapterCallbacks callbacks{NcmAdapter::NotifyReceive};
  UsbNcmHostDevice host{128,&callbacks,&adapter};
  UsbNcmHostDevice::DataBulkInPipeReadCompletetionRoutine(nullptr,&memory,64,&host);
  const bool clean=!queue.enqueued && heldReferences==0 && queue.notifications==0 &&
                   rxQueue.drops==1 && bufferPuts==0;
  std::printf("failed-enqueue notifications=%d expected=0, held-references=%d, drops=%d, puts=%d\n",
              queue.notifications,heldReferences,rxQueue.drops,bufferPuts);
  return !clean;
}
// Continuous-request-target buffers (function driver) are owned by the
// receiver once delivered: a drop must hand them back or reads starve.
static int DroppedContinuousBuffersReturnToOwner() {
  uint8_t data[64]={}; auto* owner=reinterpret_cast<DMFMODULE>(uintptr_t(0x77));
  Queue full; full.fetchStatus=STATUS_INSUFFICIENT_RESOURCES;
  RxQueue rxQueue{&full}; NcmAdapter adapter{&rxQueue};
  bufferPuts=0; NcmAdapter::NotifyReceive(&adapter,data,sizeof(data),nullptr,owner);
  assert(bufferPuts==1 && lastPutModule==owner && lastPutBuffer==data);
  assert(rxQueue.drops==1 && full.notifications==0 && !full.enqueued);
  NcmAdapter detached{nullptr};
  bufferPuts=0; NcmAdapter::NotifyReceive(&detached,data,sizeof(data),nullptr,owner);
  assert(bufferPuts==1 && lastPutBuffer==data);
  Queue open; RxQueue openQueue{&open}; NcmAdapter accepting{&openQueue};
  bufferPuts=0; NcmAdapter::NotifyReceive(&accepting,data,sizeof(data),nullptr,owner);
  assert(bufferPuts==0 && open.enqueued && open.notifications==1 && openQueue.drops==0);
  RxBufferQueueReturnBuffer(&open,&open.buffer);
  assert(bufferPuts==1 && lastPutBuffer==data && !open.enqueued);
  std::puts("dropped/detached continuous-target buffers returned exactly once PASS");
  return 0;
}
static int DetachedQueueDoesNotEnqueue() {
  Memory memory; memory.bytes.resize(128);
  Queue queue; RxQueue rxQueue{nullptr}; NcmAdapter adapter{nullptr};
  NcmAdapter::NotifyReceive(&adapter,nullptr,64,&memory,nullptr);
  adapter.m_RxQueue=&rxQueue;
  NcmAdapter::NotifyReceive(&adapter,nullptr,64,&memory,nullptr);
  assert(heldReferences==0 && !queue.enqueued && queue.fetchCalls==0);
  std::puts("detached/uninitialized RX queue: no reference or enqueue PASS");
  return 0;
}
int main() {
  const auto result16=Check<Test16>(false), result32=Check<Test32>(true);
  const auto invalid=InvalidBorrowedExtent(), failed=FailedEnqueueDoesNotNotify();
  return result16 || result32 || invalid || failed || DetachedQueueDoesNotEnqueue() ||
         DroppedContinuousBuffersReturnToOwner();
}
'''


def run_probe():
    with tempfile.TemporaryDirectory(prefix='sideline-ncm-rx-completion-') as tmp:
        cpp = Path(tmp) / 'probe.cpp'
        cpp.write_text(ntb.shim + shim + rx_struct + queue_shim + functions +
                       '\n#pragma pack(push,1)\n' + ntb.structures +
                       '\n#pragma pack(pop)\n' + ntb.template + main)
        binary = Path(tmp) / 'probe'
        subprocess.run(['clang++', '-std=c++17', '-fsanitize=address,undefined',
                        '-g', str(cpp), '-o', str(binary)], check=True)
        return subprocess.run([str(binary)]).returncode


if __name__ == '__main__':
    sys.exit(run_probe())
