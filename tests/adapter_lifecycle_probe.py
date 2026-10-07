"""Real adapter create/destroy and queue-detachment functions with OS shims.

Checks allocation/config/start failure rollback, producer-before-delete order,
repeated destruction, and old-queue cleanup preserving replacement pointers.
Does not simulate real NetAdapterCx/WDF scheduling or prove kernel load safety.
"""
from pathlib import Path
import subprocess
import tempfile
import sys
from rx_completion_probe import function_from_source, root

functions = '\n'.join([
    function_from_source(root/'adapter/adapter.cpp', 'NTSTATUS\nUsbNcmAdapterCreate('),
    function_from_source(root/'adapter/adapter.cpp', 'void\nUsbNcmAdapterDestory('),
    function_from_source(root/'host/device.cpp', 'void\nUsbNcmHostDevice::DestroyAdapter('),
    function_from_source(root/'host/device.cpp', 'NTSTATUS\nUsbNcmHostDevice::LeaveWorkingState('),
    function_from_source(root/'adapter/rxqueue.cpp', 'void\nNcmRxQueue::EvtCleanup('),
    function_from_source(root/'adapter/txqueue.cpp', 'void\nNcmTxQueue::EvtCleanup('),
])
shim = r'''
#include <cassert>
#include <cstdio>
#include <new>
#include <vector>
#include <unordered_set>
#define _In_
#define _Outptr_
#define PAGED_CODE() ((void)0)
#define NT_SUCCESS(s) ((s)>=0)
#define NCM_RETURN_IF_NOT_NT_SUCCESS_MSG(e,m) do{auto s=(e);if(!NT_SUCCESS(s))return s;}while(0)
using NTSTATUS=int;using WDFDEVICE=void*;using WDFOBJECT=void*;using NETADAPTER=void*;
constexpr auto WDF_NO_HANDLE=nullptr;
constexpr int STATUS_SUCCESS=0,STATUS_INSUFFICIENT_RESOURCES=-4,STATUS_UNSUCCESSFUL=-5;
struct NETADAPTER_INIT{};struct NETRXQUEUE_INIT{};struct NETTXQUEUE_INIT{};
struct NET_ADAPTER_DATAPATH_CALLBACKS{};struct WDF_OBJECT_ATTRIBUTES{};
#define WDF_OBJECT_ATTRIBUTES_INIT_CONTEXT_TYPE(a,t) (*(a)={})
#define NET_ADAPTER_DATAPATH_CALLBACKS_INIT(a,t,r) (*(a)={})
struct USBNCM_ADAPTER_PARAMETERS{};
struct USBNCM_ADAPTER_EVENT_CALLBACKS{int value=1;};
struct USBNCM_DEVICE_EVENT_CALLBACKS{void(*EvtUsbNcmStopReceive)(WDFDEVICE);void(*EvtUsbNcmStopTransmit)(WDFDEVICE);};
struct NcmAdapter;
struct NcmRxQueue{NcmAdapter* m_NcmAdapter;static void EvtCleanup(WDFOBJECT);static void EvtCreateRxQueue();};
struct NcmTxQueue{NcmAdapter* m_NcmAdapter;static void EvtCleanup(WDFOBJECT);static void EvtCreateTxQueue();};
static int failStage=0,initLive=0,invalidUse=0,earlyDelete=0;
static bool rxActive=false,txActive=false;
static std::vector<int> events;
static std::unordered_set<void*> liveAdapters;
struct NcmAdapter{
 WDFDEVICE m_WdfDevice;const USBNCM_DEVICE_EVENT_CALLBACKS* m_UsbNcmDeviceCallbacks;
 NcmRxQueue* m_RxQueue=nullptr;NcmTxQueue* m_TxQueue=nullptr;
 static const USBNCM_ADAPTER_EVENT_CALLBACKS s_NcmAdapterCallbacks;
 NcmAdapter(WDFDEVICE d,const USBNCM_ADAPTER_PARAMETERS*,const USBNCM_DEVICE_EVENT_CALLBACKS* c,NETADAPTER):m_WdfDevice(d),m_UsbNcmDeviceCallbacks(c){}
 WDFDEVICE GetWdfDevice(){return m_WdfDevice;}
 NTSTATUS ConfigAdapter(){return failStage==3?STATUS_UNSUCCESSFUL:STATUS_SUCCESS;}
 NTSTATUS StartAdapter(){rxActive=txActive=true;return failStage==4?STATUS_UNSUCCESSFUL:STATUS_SUCCESS;}
};
const USBNCM_ADAPTER_EVENT_CALLBACKS NcmAdapter::s_NcmAdapterCallbacks{};
static NcmAdapter* NcmGetAdapterFromHandle(NETADAPTER h){assert(liveAdapters.count(h));return static_cast<NcmAdapter*>(h);}
static NcmRxQueue* NcmGetRxQueueFromHandle(WDFOBJECT h){return static_cast<NcmRxQueue*>(h);}
static NcmTxQueue* NcmGetTxQueueFromHandle(WDFOBJECT h){return static_cast<NcmTxQueue*>(h);}
static NETADAPTER_INIT* NetAdapterInitAllocate(WDFDEVICE){if(failStage==1)return nullptr;++initLive;return new NETADAPTER_INIT;}
static void NetAdapterInitSetDatapathCallbacks(NETADAPTER_INIT* i,NET_ADAPTER_DATAPATH_CALLBACKS*){assert(i);}
static void NetAdapterInitFree(NETADAPTER_INIT* i){assert(i);--initLive;delete i;}
static NTSTATUS NetAdapterCreate(NETADAPTER_INIT*,WDF_OBJECT_ATTRIBUTES*,NETADAPTER* out){
 if(failStage==2)return STATUS_INSUFFICIENT_RESOURCES;
 *out=::operator new(sizeof(NcmAdapter));liveAdapters.insert(*out);return STATUS_SUCCESS;
}
static void NetAdapterStop(NETADAPTER h){assert(liveAdapters.count(h));events.push_back(3);}
static void WdfObjectDelete(NETADAPTER h){
 if(!liveAdapters.erase(h)){++invalidUse;return;}
 earlyDelete+=rxActive||txActive;events.push_back(4);::operator delete(h);
}
static void StopRx(WDFDEVICE){rxActive=false;events.push_back(1);}
static void StopTx(WDFDEVICE){txActive=false;events.push_back(2);}
void UsbNcmAdapterDestory(NETADAPTER);
struct UsbNcmHostDevice{
 WDFDEVICE m_WdfDevice=nullptr;NETADAPTER m_NetAdapter=nullptr;
 const USBNCM_ADAPTER_EVENT_CALLBACKS* m_NcmAdapterCallbacks=nullptr;
 void DestroyAdapter();NTSTATUS LeaveWorkingState();
 static void StopReceive(WDFDEVICE d){StopRx(d);}static void StopTransmit(WDFDEVICE d){StopTx(d);}
};
'''
main = r'''
int main(){
 USBNCM_ADAPTER_PARAMETERS params;USBNCM_DEVICE_EVENT_CALLBACKS callbacks{StopRx,StopTx};
 int checks=0;
 for(int stage=1;stage<=4;++stage){
  failStage=stage;events.clear();rxActive=txActive=false;
  NETADAPTER adapter=reinterpret_cast<void*>(1);
  auto* cb=reinterpret_cast<const USBNCM_ADAPTER_EVENT_CALLBACKS*>(1);
  auto s=UsbNcmAdapterCreate(nullptr,&params,&callbacks,&adapter,&cb);
  assert(!NT_SUCCESS(s)&&adapter==nullptr&&cb==nullptr&&initLive==0&&liveAdapters.empty());
  assert(!rxActive&&!txActive&&earlyDelete==0&&invalidUse==0);
  if(stage>=3)assert((events==std::vector<int>{1,2,3,4}));
  ++checks;std::printf("adapter failure stage=%d rollback PASS\n",stage);
 }
 failStage=0;events.clear();NETADAPTER adapter=nullptr;const USBNCM_ADAPTER_EVENT_CALLBACKS* cb=nullptr;
 assert(UsbNcmAdapterCreate(nullptr,&params,&callbacks,&adapter,&cb)==STATUS_SUCCESS);
 assert(adapter&&cb&&rxActive&&txActive);
 UsbNcmHostDevice host;host.m_NetAdapter=adapter;host.m_NcmAdapterCallbacks=cb;
 host.DestroyAdapter();host.DestroyAdapter();
 assert(host.m_NetAdapter==nullptr&&host.m_NcmAdapterCallbacks==nullptr&&liveAdapters.empty());
 assert((events==std::vector<int>{1,2,3,4})&&earlyDelete==0&&invalidUse==0);++checks;
 std::puts("producer quiescence and repeated destroy PASS");
 events.clear();rxActive=txActive=true;assert(host.LeaveWorkingState()==STATUS_SUCCESS);
 assert(!rxActive&&!txActive&&(events==std::vector<int>{1,2}));++checks;
 NcmAdapter parent(nullptr,&params,&callbacks,nullptr);
 NcmRxQueue oldRx{&parent},newRx{&parent};NcmTxQueue oldTx{&parent},newTx{&parent};
 parent.m_RxQueue=&newRx;parent.m_TxQueue=&newTx;
 NcmRxQueue::EvtCleanup(&oldRx);NcmTxQueue::EvtCleanup(&oldTx);
 assert(parent.m_RxQueue==&newRx&&parent.m_TxQueue==&newTx);++checks;
 NcmRxQueue::EvtCleanup(&newRx);NcmTxQueue::EvtCleanup(&newTx);
 assert(!parent.m_RxQueue&&!parent.m_TxQueue);++checks;
 NcmRxQueue::EvtCleanup(&newRx);NcmTxQueue::EvtCleanup(&newTx);++checks;
 std::printf("adapter lifecycle: %d checks, 0 failures\n",checks);
}
'''
def run_probe():
    with tempfile.TemporaryDirectory(prefix='sideline-ncm-lifecycle-') as tmp:
        cpp=Path(tmp)/'probe.cpp';cpp.write_text(shim+functions+main)
        binary=Path(tmp)/'probe'
        subprocess.run(['clang++','-std=c++17','-fsanitize=address,undefined','-g',str(cpp),'-o',str(binary)],check=True)
        return subprocess.run([str(binary)]).returncode

if __name__=='__main__':
    sys.exit(run_probe())
