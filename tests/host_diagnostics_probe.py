"""Run production host data-pipe diagnostics with WDF shims.

Checks that TX send/completion failures and RX continuous-reader failures are
counted and logged at a bounded rate, while observable behavior is unchanged:
every completion still returns its buffer once, send failures still return
their status, and the readers-failed callback keeps KMDF's default recovery.
Does not simulate KMDF scheduling, USB errors or pipe reset.
"""
from pathlib import Path
import subprocess
import sys
import tempfile
from rx_completion_probe import function_from_source, root

source = root/'host/device.cpp'
functions = '\n'.join([
    function_from_source(source, 'static\nbool\nShouldLogOccurrence('),
    function_from_source(source, 'static\nULONG64\nElapsedMs('),
    function_from_source(source, 'BOOLEAN\nUsbNcmHostDevice::DataBulkInPipeReadersFailed('),
    function_from_source(source, 'void\nUsbNcmHostDevice::TransmitFramesCompetion('),
    function_from_source(source, 'NTSTATUS\nUsbNcmHostDevice::TransmitFrames('),
])
shim = r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include "%s"
#define _In_
#define _Use_decl_annotations_
#define NT_SUCCESS(s) ((s)>=0)
#define NT_FRE_ASSERT(e) assert(e)
using NTSTATUS=int32_t;using LONG=int32_t;using USBD_STATUS=int32_t;using BOOLEAN=bool;using ULONG=uint32_t;
using LONG64=int64_t;using ULONG64=uint64_t;
using UCHAR=uint8_t;using VOID=void;
using WDFREQUEST=void*;using WDFIOTARGET=void*;using WDFUSBPIPE=void*;using WDFDEVICE=void*;
using WDFMEMORY=void*;using WDFCONTEXT=void*;using NETADAPTER=void*;
constexpr BOOLEAN TRUE=true;
constexpr NTSTATUS STATUS_SUCCESS=0,STATUS_CANCELLED=int32_t(0xC0000120),STATUS_IO_TIMEOUT=int32_t(0xC00000B5),
 STATUS_IO_DEVICE_ERROR=int32_t(0xC0000185),STATUS_DEVICE_NOT_READY=int32_t(0xC00000A3),
 STATUS_INVALID_DEVICE_STATE=int32_t(0xC0000184),STATUS_INSUFFICIENT_RESOURCES=int32_t(0xC000009A);
constexpr USBD_STATUS USBD_STATUS_STALL_PID=int32_t(0xC0000004);
static int logs=0;
static int DbgPrintShim(const char*,...){++logs;return 0;}
#define DbgPrint DbgPrintShim
static LONG InterlockedIncrement(LONG* p){return ++*p;}
static LONG InterlockedDecrement(LONG* p){return --*p;}
static LONG InterlockedCompareExchange(LONG* p,LONG x,LONG c){LONG o=*p;if(o==c)*p=x;return o;}
static LONG64 InterlockedExchange64(LONG64* p,LONG64 v){LONG64 o=*p;*p=v;return o;}
static LONG64 InterlockedCompareExchange64(LONG64* p,LONG64 x,LONG64 c){LONG64 o=*p;if(o==c)*p=x;return o;}
static ULONG64 KeQueryInterruptTime(){return 1;}
struct EX_RUNDOWN_REF{int active;};
static int gateClosed=0;
static BOOLEAN ExAcquireRundownProtection(EX_RUNDOWN_REF* r){if(gateClosed)return false;++r->active;return true;}
static void ExReleaseRundownProtection(EX_RUNDOWN_REF* r){assert(r->active>0);--r->active;}
struct WDF_USB_REQUEST_COMPLETION_PARAMS{USBD_STATUS UsbdStatus;};
struct WDF_REQUEST_COMPLETION_PARAMS{
 struct{NTSTATUS Status;}IoStatus;
 struct{struct{WDF_USB_REQUEST_COMPLETION_PARAMS* Completion;}Usb;}Parameters;
};
using PWDF_REQUEST_COMPLETION_PARAMS=WDF_REQUEST_COMPLETION_PARAMS*;
struct TX_BUFFER_REQUEST{WDFREQUEST Request;size_t BufferLength;WDFMEMORY BufferWdfMemory;size_t TransferLength;UCHAR Buffer[2048];};
struct WDFMEMORY_OFFSET{size_t BufferOffset,BufferLength;};
struct WDF_REQUEST_SEND_OPTIONS{ULONG Flags;long long Timeout;};
constexpr ULONG WDF_REQUEST_SEND_OPTION_TIMEOUT=1;
#define WDF_REQUEST_SEND_OPTIONS_INIT(o,f) ((o)->Flags=(f),(o)->Timeout=0)
#define WDF_REQUEST_SEND_OPTIONS_SET_TIMEOUT(o,t) ((o)->Timeout=(t))
#define WDF_REL_TIMEOUT_IN_SEC(s) (-10000000LL*(s))
static int completions=0,routinesSet=0;static bool sendAccepted=true;
static NTSTATUS formatStatus=STATUS_SUCCESS,sendStatus=STATUS_SUCCESS;
static size_t formattedLength=0;
struct AdapterCallbacks{void(*EvtUsbNcmAdapterNotifyTransmitCompletion)(NETADAPTER,TX_BUFFER_REQUEST*);};
static void NotifyTransmitCompletion(NETADAPTER,TX_BUFFER_REQUEST*){++completions;}
static AdapterCallbacks adapterCallbacks{NotifyTransmitCompletion};
struct UsbNcmHostDevice{
 WDFUSBPIPE m_DataBulkOutPipe=reinterpret_cast<void*>(7);ULONG m_DataBulkOutPipeMaximumPacketSize=512;
 AdapterCallbacks* m_NcmAdapterCallbacks=&adapterCallbacks;NETADAPTER m_NetAdapter=nullptr;
 LONG m_TxSendFailures=0,m_TxCompletionFailures=0,m_TxCancellations=0,m_TxTimeouts=0,m_RxReadersFailures=0;
 ULONG m_DataPathDebug=0;LONG m_TxInflight=0,m_TxInflightPeak=0,m_TxSuccesses=0,m_TxFirstFailureLogged=0,m_TxAdmissionRejects=0;
 LONG64 m_TxLastSuccessTime=0;EX_RUNDOWN_REF m_TxAdmission{};void* m_TxRecoveryWorkItem=nullptr;
 void RequestOutPipeRecovery(NTSTATUS,USBD_STATUS){assert(!"recovery is off in this probe");}
 static BOOLEAN DataBulkInPipeReadersFailed(WDFUSBPIPE,NTSTATUS,USBD_STATUS);
 static VOID TransmitFramesCompetion(WDFREQUEST,WDFIOTARGET,PWDF_REQUEST_COMPLETION_PARAMS,WDFCONTEXT);
 static NTSTATUS TransmitFrames(WDFDEVICE,TX_BUFFER_REQUEST*);
};
static UsbNcmHostDevice* current=nullptr;
static UsbNcmHostDevice* NcmGetHostDeviceFromHandle(WDFDEVICE d){assert(d==current);return current;}
static WDFDEVICE WdfIoTargetGetDevice(WDFIOTARGET t){assert(t==reinterpret_cast<void*>(9));return current;}
static WDFIOTARGET WdfUsbTargetPipeGetIoTarget(WDFUSBPIPE){return reinterpret_cast<void*>(9);}
static void WdfRequestSetCompletionRoutine(WDFREQUEST,void(*)(WDFREQUEST,WDFIOTARGET,PWDF_REQUEST_COMPLETION_PARAMS,WDFCONTEXT),void*){++routinesSet;}
static NTSTATUS WdfUsbTargetPipeFormatRequestForWrite(WDFUSBPIPE,WDFREQUEST,WDFMEMORY,WDFMEMORY_OFFSET* o){formattedLength=o->BufferLength;return formatStatus;}
static bool WdfRequestSend(WDFREQUEST,WDFIOTARGET,WDF_REQUEST_SEND_OPTIONS* o){assert(o->Timeout==-50000000LL);return sendAccepted;}
static NTSTATUS WdfRequestGetStatus(WDFREQUEST){return sendStatus;}
'''
shim = shim.replace('%s', str(root/'host/out_pipe_policy.h'))
main = r'''
static int checks=0;
#define CHECK(e) do{++checks;assert(e);}while(0)
static WDF_REQUEST_COMPLETION_PARAMS Params(NTSTATUS s,WDF_USB_REQUEST_COMPLETION_PARAMS* u){
 WDF_REQUEST_COMPLETION_PARAMS p{};p.IoStatus.Status=s;p.Parameters.Usb.Completion=u;return p;
}
int main(){
 int logged=0;
 for(LONG n=-2;n<=1000;++n)logged+=ShouldLogOccurrence(n);
 CHECK(logged==10); // 1,2,4,...,512
 UsbNcmHostDevice host;current=&host;TX_BUFFER_REQUEST request{};
 WDF_USB_REQUEST_COMPLETION_PARAMS usb{USBD_STATUS_STALL_PID};
 auto ok=Params(STATUS_SUCCESS,&usb);
 UsbNcmHostDevice::TransmitFramesCompetion(nullptr,reinterpret_cast<void*>(9),&ok,&request);
 CHECK(completions==1&&logs==0&&host.m_TxCompletionFailures==0&&host.m_TxCancellations==0);
 for(int i=0;i<100;++i){
  auto cancelled=Params(STATUS_CANCELLED,&usb);
  UsbNcmHostDevice::TransmitFramesCompetion(nullptr,reinterpret_cast<void*>(9),&cancelled,&request);
 }
 CHECK(completions==101&&host.m_TxCancellations==100&&host.m_TxCompletionFailures==0&&logs==7);
 logs=0;
 for(int i=0;i<3;++i){
  auto failed=Params(STATUS_IO_DEVICE_ERROR,i==2?nullptr:&usb);
  UsbNcmHostDevice::TransmitFramesCompetion(nullptr,reinterpret_cast<void*>(9),&failed,&request);
 }
 CHECK(completions==104&&host.m_TxCompletionFailures==3&&logs==2);
 logs=0;
 for(int i=0;i<4;++i){auto timedOut=Params(STATUS_IO_TIMEOUT,&usb);
  UsbNcmHostDevice::TransmitFramesCompetion(nullptr,reinterpret_cast<void*>(9),&timedOut,&request);}
 CHECK(completions==108&&host.m_TxTimeouts==4&&host.m_TxCompletionFailures==3&&host.m_TxCancellations==100&&logs==3);
 std::puts("TX completion: buffer returned once per completion; cancel/timeout/error counted apart, logs bounded PASS");
 logs=0;
 for(int i=0;i<5;++i)CHECK(UsbNcmHostDevice::DataBulkInPipeReadersFailed(nullptr,STATUS_IO_DEVICE_ERROR,USBD_STATUS_STALL_PID)==TRUE);
 CHECK(host.m_RxReadersFailures==5&&logs==3);
 std::puts("RX readers failed: counted, logged, default KMDF recovery kept (TRUE) PASS");
 logs=0;completions=0;
 request.BufferLength=1024;request.TransferLength=512;
 CHECK(UsbNcmHostDevice::TransmitFrames(current,&request)==STATUS_SUCCESS);
 CHECK(formattedLength==513&&request.Buffer[512]==0&&host.m_TxSendFailures==0&&logs==0); // ZLP pad unchanged
 sendAccepted=false;sendStatus=STATUS_INVALID_DEVICE_STATE;request.TransferLength=100;
 CHECK(UsbNcmHostDevice::TransmitFrames(current,&request)==STATUS_INVALID_DEVICE_STATE);
 CHECK(host.m_TxSendFailures==1&&logs==1&&completions==0);
 sendAccepted=true;formatStatus=STATUS_INSUFFICIENT_RESOURCES;
 CHECK(UsbNcmHostDevice::TransmitFrames(current,&request)==STATUS_INSUFFICIENT_RESOURCES);
 CHECK(host.m_TxSendFailures==2&&logs==2);
 formatStatus=STATUS_SUCCESS;host.m_DataBulkOutPipe=nullptr;
 CHECK(UsbNcmHostDevice::TransmitFrames(current,&request)==STATUS_DEVICE_NOT_READY);
 CHECK(host.m_TxSendFailures==2); // no pipe is not a send failure
 gateClosed=1;CHECK(UsbNcmHostDevice::TransmitFrames(current,&request)==STATUS_DEVICE_NOT_READY);
 CHECK(host.m_TxSendFailures==2&&host.m_TxAdmissionRejects==1&&host.m_TxAdmission.active==0);
 std::puts("TX send: failure status returned unchanged and counted PASS");
 std::printf("host data-pipe diagnostics: %d checks, 0 failures\n",checks);
}
'''


def run_probe():
    with tempfile.TemporaryDirectory(prefix='sideline-ncm-diag-') as tmp:
        cpp = Path(tmp)/'probe.cpp'
        cpp.write_text(shim+functions+main)
        binary = Path(tmp)/'probe'
        subprocess.run(['clang++','-std=c++17','-fsanitize=address,undefined','-g',
                        str(cpp),'-o',str(binary)],check=True)
        return subprocess.run([str(binary)]).returncode


if __name__ == '__main__':
    sys.exit(run_probe())
