"""Run the production bulk-OUT send, completion, lifecycle and recovery code
against a small KMDF model, under ASan/UBSan and real threads.

The model follows KMDF behavior read from the open-source framework:
a stopped I/O target queues new sends (STATUS_WDF_QUEUED) instead of failing
them; WdfIoTargetStop(CancelSentIo) returns only after every sent request's
completion routine has run; WdfRequestSend may run the completion inline and
does not run it when it returns FALSE. It also checks the driver's rules:
no wait lock on the send/completion path, no blocking call at "dispatch",
work-item flush outside the lock, no send during reset, no access to a request
after it went back to the pool, and no port or device reset (those DDIs are
deliberately absent, so calling one fails the build).

A second check compiles the same TX functions from the frozen PR #1 head and
requires switch value 0 to produce the identical I/O trace.

Limits: Linux threads and shims cannot prove KMDF scheduling, IRQL rules,
Driver Verifier results or USB hardware behavior. adapter/txqueue.cpp's caller
contract (return the buffer when TransmitFrames fails) is mirrored, not run.
"""
from pathlib import Path
import subprocess
import sys
import os
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DRIVER = ROOT/'NCM-Driver-for-Windows'
FROZEN = '2327f448cf6c755d864fdb795ad6f6a961efe3df'

TX_FUNCTIONS = [
    'static\nbool\nShouldLogOccurrence(',
    'NTSTATUS\nStartPipe(',
    'void\nStopPipe(',
    'void\nUsbNcmHostDevice::StartTransmit(',
    'void\nUsbNcmHostDevice::StopTransmit(',
    'void\nUsbNcmHostDevice::TransmitFramesCompetion(',
    'NTSTATUS\nUsbNcmHostDevice::TransmitFrames(',
]
NEW_FUNCTIONS = ['static\nULONG64\nElapsedMs('] + TX_FUNCTIONS + [
    'void\nUsbNcmHostDevice::StopReceive(',
    'NTSTATUS\nUsbNcmHostDevice::LeaveWorkingState(',
    'NTSTATUS\nUsbNcmHostDevice::InitializeDataPathControl(',
    'void\nUsbNcmHostDevice::BeginD0Session(',
    'void\nUsbNcmHostDevice::CloseTxAdmissionLocked(',
    'void\nUsbNcmHostDevice::OpenTxAdmissionLocked(',
    'void\nUsbNcmHostDevice::RequestOutPipeRecovery(',
    'VOID\nUsbNcmHostDevice::OutPipeRecoveryWorkItem(',
    'void\nUsbNcmHostDevice::RecoverOutPipe(',
]


def extract(text, signature):
    start = text.index(signature)
    brace = text.index('{', start)
    depth, end = 1, brace + 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[start:end]


def class_text(header):
    start = header.index('class UsbNcmHostDevice')
    return header[start:header.index('\n};\n', start) + 4]


def frozen(path):
    return subprocess.run(['git', 'show', f'{FROZEN}:{path}'], cwd=ROOT, check=True,
                          capture_output=True, text=True).stdout


SHIM = r'''
#include <atomic>
#include <cassert>
#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <cwchar>
#include <deque>
#include <functional>
#include <mutex>
#include <random>
#include <string>
#include <thread>
#include <vector>
#define _In_
#define _In_opt_
#define _Out_opt_
#define _Use_decl_annotations_
#define _IRQL_requires_max_(x)
#define _IRQL_requires_(x)
#define PAGED
#define PAGEDX
#define PAGED_CODE() AssertPassive()
#define NT_SUCCESS(s) ((NTSTATUS)(s)>=0)
#define NT_FRE_ASSERT(e) assert(e)
#define NCM_RETURN_IF_NOT_NT_SUCCESS_MSG(e,m) do{NTSTATUS s_=(e);if(!NT_SUCCESS(s_))return s_;}while(0)
using NTSTATUS=int32_t;using LONG=int32_t;using ULONG=uint32_t;using LONG64=int64_t;using ULONG64=uint64_t;
using USBD_STATUS=int32_t;using BOOLEAN=bool;using UCHAR=uint8_t;using BYTE=uint8_t;using UINT8=uint8_t;
using UINT16=uint16_t;using UINT32=uint32_t;using PULONG=ULONG*;using VOID=void;
constexpr bool TRUE=true,FALSE=false;
#define S(x) ((NTSTATUS)(x##u))
constexpr NTSTATUS STATUS_SUCCESS=0,STATUS_UNSUCCESSFUL=S(0xC0000001),STATUS_CANCELLED=S(0xC0000120),
 STATUS_IO_TIMEOUT=S(0xC00000B5),STATUS_DEVICE_NOT_READY=S(0xC00000A3),STATUS_INVALID_DEVICE_STATE=S(0xC0000184),
 STATUS_INSUFFICIENT_RESOURCES=S(0xC000009A),STATUS_OBJECT_NAME_NOT_FOUND=S(0xC0000034),
 STATUS_NO_SUCH_DEVICE=S(0xC000000E),STATUS_DEVICE_NOT_CONNECTED=S(0xC000009D),STATUS_DEVICE_REMOVED=S(0xC00002B6),
 STATUS_DELETE_PENDING=S(0xC0000056),STATUS_DEVICE_DOES_NOT_EXIST=S(0xC00000C0),STATUS_DEVICE_POWERED_OFF=S(0x8000000F),
 STATUS_IO_DEVICE_ERROR=S(0xC0000185);
constexpr USBD_STATUS USBD_STATUS_XACT_ERROR=S(0xC0000011),USBD_STATUS_CANCELED=S(0xC0010000),
 USBD_STATUS_STALL_PID=S(0xC0000004),USBD_STATUS_DEVICE_GONE=S(0xC0007000),USBD_STATUS_BABBLE_DETECTED=S(0xC0000012);

// --- execution context checks ---
static thread_local bool t_dispatch=false;      // send or completion path
static thread_local bool t_inCompletion=false;
static thread_local int t_locksHeld=0;
static void AssertPassive(){assert(!t_dispatch);}
struct DispatchScope{bool old;DispatchScope():old(t_dispatch){t_dispatch=true;}~DispatchScope(){t_dispatch=old;}};

// --- trace and logs ---
static std::mutex g_traceLock;
static std::vector<std::string> g_trace,g_logs;
static void Trace(const std::string& s){std::lock_guard<std::mutex> l(g_traceLock);g_trace.push_back(s);}
static int DbgPrint(const char* f,...){std::lock_guard<std::mutex> l(g_traceLock);g_logs.push_back(f);return 0;}
static int LogsWith(const char* text){std::lock_guard<std::mutex> l(g_traceLock);int n=0;for(auto& s:g_logs)n+=s.find(text)!=std::string::npos;return n;}
static int TraceCount(const std::string& p){std::lock_guard<std::mutex> l(g_traceLock);int n=0;for(auto& s:g_trace)n+=s.rfind(p,0)==0;return n;}
static std::string Hex(int32_t v){char b[16];std::snprintf(b,sizeof b,"%08X",(unsigned)v);return b;}

// --- interlocked, clock ---
static LONG InterlockedIncrement(LONG* p){return __atomic_add_fetch(p,1,__ATOMIC_SEQ_CST);}
static LONG InterlockedDecrement(LONG* p){return __atomic_sub_fetch(p,1,__ATOMIC_SEQ_CST);}
static LONG InterlockedExchange(LONG* p,LONG v){return __atomic_exchange_n(p,v,__ATOMIC_SEQ_CST);}
static LONG InterlockedCompareExchange(LONG* p,LONG x,LONG c){__atomic_compare_exchange_n(p,&c,x,false,__ATOMIC_SEQ_CST,__ATOMIC_SEQ_CST);return c;}
static LONG64 InterlockedExchange64(LONG64* p,LONG64 v){return __atomic_exchange_n(p,v,__ATOMIC_SEQ_CST);}
static LONG64 InterlockedCompareExchange64(LONG64* p,LONG64 x,LONG64 c){__atomic_compare_exchange_n(p,&c,x,false,__ATOMIC_SEQ_CST,__ATOMIC_SEQ_CST);return c;}
static std::atomic<ULONG64> g_clock{1};
static ULONG64 KeQueryInterruptTime(){return g_clock.load();}
static void AdvanceSeconds(int s){g_clock+=ULONG64(s)*10000000ull;}

// --- rundown protection (admission gate) ---
struct EX_RUNDOWN_REF{LONG active;bool closed;bool closing;};
static std::mutex g_rundownLock;static std::condition_variable g_rundownCv;
static void ExInitializeRundownProtection(EX_RUNDOWN_REF* r){std::lock_guard<std::mutex> l(g_rundownLock);*r={0,false,false};}
static BOOLEAN ExAcquireRundownProtection(EX_RUNDOWN_REF* r){std::lock_guard<std::mutex> l(g_rundownLock);if(r->closed||r->closing)return false;++r->active;return true;}
static void ExReleaseRundownProtection(EX_RUNDOWN_REF* r){std::lock_guard<std::mutex> l(g_rundownLock);assert(r->active>0);--r->active;g_rundownCv.notify_all();}
static void ExWaitForRundownProtectionRelease(EX_RUNDOWN_REF* r){
 AssertPassive();std::unique_lock<std::mutex> l(g_rundownLock);assert(!r->closed);r->closing=true;
 g_rundownCv.wait(l,[&]{return r->active==0;});r->closing=false;r->closed=true;}
static void ExReInitializeRundownProtection(EX_RUNDOWN_REF* r){std::lock_guard<std::mutex> l(g_rundownLock);assert(r->closed&&r->active==0);r->closed=false;}
static bool GateClosing(EX_RUNDOWN_REF* r){std::lock_guard<std::mutex> l(g_rundownLock);return r->closing||r->closed;}

// --- WDF objects ---
class UsbNcmHostDevice;
struct FakeDevice{UsbNcmHostDevice* host=nullptr;};
struct FakeRequest;struct FakeTarget;
using WDFDEVICE=FakeDevice*;using WDFIOTARGET=FakeTarget*;using WDFREQUEST=FakeRequest*;
using WDFMEMORY=void*;using WDFCONTEXT=void*;using WDFOBJECT=void*;using NETADAPTER=void*;
using WDFUSBDEVICE=void*;using WDFUSBINTERFACE=void*;
struct WDF_USB_REQUEST_COMPLETION_PARAMS{USBD_STATUS UsbdStatus;};
struct WDF_REQUEST_COMPLETION_PARAMS{struct{NTSTATUS Status;}IoStatus;struct{struct{WDF_USB_REQUEST_COMPLETION_PARAMS* Completion;}Usb;}Parameters;};
using PWDF_REQUEST_COMPLETION_PARAMS=WDF_REQUEST_COMPLETION_PARAMS*;
using CompletionFn=void(*)(WDFREQUEST,WDFIOTARGET,PWDF_REQUEST_COMPLETION_PARAMS,WDFCONTEXT);
struct FakeRequest{int id=0;CompletionFn fn=nullptr;void* ctx=nullptr;NTSTATUS status=0;std::atomic<bool> inPool{true};};
struct TX_BUFFER_REQUEST{WDFREQUEST Request=nullptr;size_t BufferLength=0;WDFMEMORY BufferWdfMemory=nullptr;size_t TransferLength=0;UCHAR Buffer[2048];};
struct FakeTarget{FakeDevice* device=nullptr;bool started=true;std::deque<FakeRequest*> queued;std::vector<FakeRequest*> sent;
 int completing=0;bool resetting=false;int sendsDuringReset=0;int sendsWhileStopped=0;};
struct FakePipe{FakeTarget target;std::atomic<bool> valid{true};};
using WDFUSBPIPE=FakePipe*;
static std::mutex g_m;static std::condition_variable g_cv;

enum class SendMode{Pend,InlineSuccess,InlineXact,Reject};
static std::atomic<SendMode> g_sendMode{SendMode::Pend};
static NTSTATUS g_formatStatus=STATUS_SUCCESS;
static std::vector<NTSTATUS> g_startResults;   // consumed per WdfIoTargetStart; empty = success
static NTSTATUS g_resetResult=STATUS_SUCCESS;
static std::function<void()> g_sendHook,g_resetHook;static std::atomic<bool> g_sendHookArmed{false};
static std::atomic<int> g_sendCalls{0};

static void CheckCountedBeforeCompletion(FakeTarget* t);
static void Complete(FakeRequest* r,FakeTarget* t,NTSTATUS s,USBD_STATUS u){
 assert(!r->inPool);CheckCountedBeforeCompletion(t);CompletionFn fn=r->fn;void* ctx=r->ctx;r->fn=nullptr;assert(fn);
 WDF_USB_REQUEST_COMPLETION_PARAMS usb{u};WDF_REQUEST_COMPLETION_PARAMS p{};p.IoStatus.Status=s;p.Parameters.Usb.Completion=&usb;
 DispatchScope d;bool old=t_inCompletion;t_inCompletion=true;fn(r,t,&p,ctx);t_inCompletion=old;}
// Complete up to n sent requests from another "thread" of the USB stack.
static int CompleteSent(FakeTarget* t,int n,NTSTATUS s,USBD_STATUS u){
 std::vector<FakeRequest*> batch;{std::lock_guard<std::mutex> l(g_m);
  while(n-- >0&&!t->sent.empty()){batch.push_back(t->sent.front());t->sent.erase(t->sent.begin());}
  t->completing+=(int)batch.size();}
 for(auto* r:batch){Complete(r,t,s,u);std::lock_guard<std::mutex> l(g_m);--t->completing;g_cv.notify_all();}
 return (int)batch.size();}
static size_t SentCount(FakeTarget* t){std::lock_guard<std::mutex> l(g_m);return t->sent.size();}

struct WDF_REQUEST_SEND_OPTIONS{ULONG Flags;LONG64 Timeout;};
constexpr ULONG WDF_REQUEST_SEND_OPTION_TIMEOUT=1;
#define WDF_REQUEST_SEND_OPTIONS_INIT(o,f) ((o)->Flags=(f),(o)->Timeout=0)
#define WDF_REQUEST_SEND_OPTIONS_SET_TIMEOUT(o,t) ((o)->Timeout=(t))
#define WDF_REL_TIMEOUT_IN_SEC(s) (-10000000LL*(s))
struct WDFMEMORY_OFFSET{size_t BufferOffset,BufferLength;};
enum WDF_IO_TARGET_SENT_IO_ACTION{WdfIoTargetCancelSentIo=1};
#define WDF_NO_HANDLE nullptr

static WDFIOTARGET WdfUsbTargetPipeGetIoTarget(WDFUSBPIPE p){assert(p&&p->valid);return &p->target;}
static WDFDEVICE WdfIoTargetGetDevice(WDFIOTARGET t){return t->device;}
static void WdfRequestSetCompletionRoutine(WDFREQUEST r,CompletionFn fn,void* ctx){assert(!r->inPool);r->fn=fn;r->ctx=ctx;}
static NTSTATUS WdfUsbTargetPipeFormatRequestForWrite(WDFUSBPIPE p,WDFREQUEST r,WDFMEMORY,WDFMEMORY_OFFSET* o){
 assert(p->valid&&!r->inPool);Trace("format "+std::to_string(r->id)+" len "+std::to_string(o->BufferLength));return g_formatStatus;}
static bool WdfRequestSend(WDFREQUEST r,WDFIOTARGET t,WDF_REQUEST_SEND_OPTIONS* o){
 assert(!r->inPool&&o->Flags==WDF_REQUEST_SEND_OPTION_TIMEOUT&&o->Timeout==-50000000LL);
 ++g_sendCalls;Trace("send "+std::to_string(r->id));
 if(g_sendHookArmed.exchange(false)){auto hook=std::move(g_sendHook);hook();}
 std::unique_lock<std::mutex> l(g_m);
 if(t->resetting)++t->sendsDuringReset;
 if(!t->started){++t->sendsWhileStopped;t->queued.push_back(r);Trace("queued "+std::to_string(r->id));return true;}
 switch(g_sendMode.load()){
 case SendMode::Reject:r->status=STATUS_INVALID_DEVICE_STATE;return false;
 case SendMode::InlineSuccess:l.unlock();Complete(r,t,STATUS_SUCCESS,0);return true;
 case SendMode::InlineXact:l.unlock();Complete(r,t,STATUS_UNSUCCESSFUL,USBD_STATUS_XACT_ERROR);return true;
 default:t->sent.push_back(r);return true;}}
static NTSTATUS WdfRequestGetStatus(WDFREQUEST r){assert(!r->inPool);Trace("getstatus "+std::to_string(r->id));return r->status;}
static void WdfIoTargetStop(WDFIOTARGET t,WDF_IO_TARGET_SENT_IO_ACTION a){
 AssertPassive();assert(a==WdfIoTargetCancelSentIo);Trace("stop");
 std::vector<FakeRequest*> batch;{std::lock_guard<std::mutex> l(g_m);t->started=false;batch.swap(t->sent);}
 for(auto* r:batch)Complete(r,t,STATUS_CANCELLED,USBD_STATUS_CANCELED);
 std::unique_lock<std::mutex> l(g_m);g_cv.wait(l,[&]{return t->completing==0;});}
static NTSTATUS WdfIoTargetStart(WDFIOTARGET t){
 NTSTATUS s=STATUS_SUCCESS;{std::lock_guard<std::mutex> l(g_m);if(!g_startResults.empty()){s=g_startResults.front();g_startResults.erase(g_startResults.begin());}}
 Trace("start "+Hex(s));
 if(NT_SUCCESS(s)){std::lock_guard<std::mutex> l(g_m);t->started=true;while(!t->queued.empty()){t->sent.push_back(t->queued.front());t->queued.pop_front();}}
 return s;}
static NTSTATUS WdfUsbTargetPipeResetSynchronously(WDFUSBPIPE p,WDFREQUEST r,WDF_REQUEST_SEND_OPTIONS* o){
 AssertPassive();assert(p->valid&&r==nullptr&&o&&o->Flags==WDF_REQUEST_SEND_OPTION_TIMEOUT&&o->Timeout==-20000000LL);
 Trace("reset");
 {std::lock_guard<std::mutex> l(g_m);assert(!p->target.started&&p->target.sent.empty());p->target.resetting=true;}
 {auto hook=g_resetHook;if(hook)hook();}
 {std::lock_guard<std::mutex> l(g_m);p->target.resetting=false;}
 return g_resetResult;}

// Wait locks: PASSIVE only, never recursive, never on the send/completion path.
struct FakeWaitLock{std::mutex m;std::atomic<std::thread::id> owner{};};
using WDFWAITLOCK=FakeWaitLock*;
struct WDF_OBJECT_ATTRIBUTES{void* ParentObject;};
#define WDF_OBJECT_ATTRIBUTES_INIT(a) ((a)->ParentObject=nullptr)
#define WDF_NO_OBJECT_ATTRIBUTES nullptr
static NTSTATUS g_waitLockCreateStatus=STATUS_SUCCESS;
static NTSTATUS WdfWaitLockCreate(WDF_OBJECT_ATTRIBUTES*,WDFWAITLOCK* l){if(!NT_SUCCESS(g_waitLockCreateStatus))return g_waitLockCreateStatus;*l=new FakeWaitLock;return STATUS_SUCCESS;}
static void WdfWaitLockAcquire(WDFWAITLOCK l,void*){AssertPassive();assert(!t_inCompletion);assert(l->owner.load()!=std::this_thread::get_id());
 l->m.lock();l->owner=std::this_thread::get_id();++t_locksHeld;}
static void WdfWaitLockRelease(WDFWAITLOCK l){assert(l->owner.load()==std::this_thread::get_id());l->owner=std::thread::id();--t_locksHeld;l->m.unlock();}

// Work items: run by a test "worker" or by flush; never inline at enqueue.
struct FakeWorkItem;using WDFWORKITEM=FakeWorkItem*;
using WorkFn=void(WDFWORKITEM);
struct FakeWorkItem{WorkFn* fn=nullptr;FakeDevice* parent=nullptr;bool queued=false;bool running=false;int enqueues=0;};
typedef VOID EVT_WDF_WORKITEM(WDFWORKITEM);
struct WDF_WORKITEM_CONFIG{WorkFn* EvtWorkItemFunc;bool AutomaticSerialization;};
#define WDF_WORKITEM_CONFIG_INIT(c,f) ((c)->EvtWorkItemFunc=(f),(c)->AutomaticSerialization=true)
static NTSTATUS g_workItemCreateStatus=STATUS_SUCCESS;static int g_workItemCreates=0;
static NTSTATUS WdfWorkItemCreate(WDF_WORKITEM_CONFIG* c,WDF_OBJECT_ATTRIBUTES* a,WDFWORKITEM* w){
 AssertPassive();assert(!c->AutomaticSerialization&&a&&a->ParentObject);++g_workItemCreates;
 if(!NT_SUCCESS(g_workItemCreateStatus))return g_workItemCreateStatus;
 *w=new FakeWorkItem;(*w)->fn=c->EvtWorkItemFunc;(*w)->parent=(FakeDevice*)a->ParentObject;return STATUS_SUCCESS;}
static void WdfWorkItemEnqueue(WDFWORKITEM w){std::lock_guard<std::mutex> l(g_m);++w->enqueues;w->queued=true;g_cv.notify_all();}
static WDFOBJECT WdfWorkItemGetParentObject(WDFWORKITEM w){return w->parent;}
static bool RunQueuedWorkItem(WDFWORKITEM w){
 {std::lock_guard<std::mutex> l(g_m);if(!w->queued||w->running)return false;w->queued=false;w->running=true;}
 bool old=t_dispatch;t_dispatch=false;w->fn(w);t_dispatch=old;
 std::lock_guard<std::mutex> l(g_m);w->running=false;g_cv.notify_all();return true;}
static void WdfWorkItemFlush(WDFWORKITEM w){
 AssertPassive();assert(t_locksHeld==0); // a queued item needs the lifecycle lock
 Trace("flush");RunQueuedWorkItem(w);
 std::unique_lock<std::mutex> l(g_m);g_cv.wait(l,[&]{return !w->running&&!w->queued;});}
static int Enqueues(WDFWORKITEM w){std::lock_guard<std::mutex> l(g_m);return w?w->enqueues:0;}

// Registry
struct UNICODE_STRING{const wchar_t* Buffer;};
#define DECLARE_CONST_UNICODE_STRING(n,s) const UNICODE_STRING n{s}
struct FakeKey{};using WDFKEY=FakeKey*;
constexpr ULONG PLUGPLAY_REGKEY_DEVICE=1,KEY_READ=0x20019;
static NTSTATUS g_regOpenStatus=STATUS_SUCCESS;static bool g_regHasValue=false;static ULONG g_regValue=0;static int g_regCloses=0;
static FakeKey g_key;
static NTSTATUS WdfDeviceOpenRegistryKey(WDFDEVICE,ULONG t,ULONG a,void*,WDFKEY* k){
 AssertPassive();assert(t==PLUGPLAY_REGKEY_DEVICE&&a==KEY_READ);if(!NT_SUCCESS(g_regOpenStatus))return g_regOpenStatus;*k=&g_key;return STATUS_SUCCESS;}
static NTSTATUS WdfRegistryQueryULong(WDFKEY k,const UNICODE_STRING* n,ULONG* v){
 assert(k==&g_key&&std::wcscmp(n->Buffer,L"Sideline1902DataPathDebug")==0);
 if(!g_regHasValue)return STATUS_OBJECT_NAME_NOT_FOUND;*v=g_regValue;return STATUS_SUCCESS;}
static void WdfRegistryClose(WDFKEY k){assert(k==&g_key);++g_regCloses;}

// Types the class declaration mentions.
enum WDF_POWER_DEVICE_STATE{WdfPowerDeviceD3Final=5};
enum WDF_USB_BMREQUEST_DIRECTION{BmRequestHostToDevice};
enum WDF_USB_BMREQUEST_RECIPIENT{BmRequestToInterface};
using PWDF_MEMORY_DESCRIPTOR=void*;
struct NTB_PARAMETERS{UINT32 dwNtbInMaxSize;};
constexpr int ETH_LENGTH_OF_ADDRESS=6;
struct USBNCM_DEVICE_EVENT_CALLBACKS{ULONG Size;};
struct USBNCM_ADAPTER_EVENT_CALLBACKS{void(*EvtUsbNcmAdapterNotifyTransmitCompletion)(NETADAPTER,TX_BUFFER_REQUEST*);};
typedef BOOLEAN EVT_WDF_USB_READERS_FAILED(WDFUSBPIPE,NTSTATUS,USBD_STATUS);
'''

COMMON = r'''
static UsbNcmHostDevice* NcmGetHostDeviceFromHandle(WDFDEVICE d){return d->host;}
// Every completing request must already be counted as inflight.
#ifdef FROZEN_HEAD
static void CheckCountedBeforeCompletion(FakeTarget*){}
#else
static void CheckCountedBeforeCompletion(FakeTarget* t){assert(__atomic_load_n(&t->device->host->m_TxInflight,__ATOMIC_SEQ_CST)>0);}
#endif

// TX buffer pool and adapter completion, mirroring adapter/txqueue.cpp and
// NcmAdapter::NotifyTransmitCompletion: a buffer is owned by the driver from
// Get until exactly one return, by the completion or by the failed caller.
static std::mutex g_poolLock;static std::vector<TX_BUFFER_REQUEST*> g_pool;static int g_poolSize=0;
static std::atomic<int> g_returns{0};
static void PoolInit(int n){g_poolSize=n;for(int i=0;i<n;++i){auto* b=new TX_BUFFER_REQUEST;b->Request=new FakeRequest;b->Request->id=i;b->BufferLength=sizeof b->Buffer;g_pool.push_back(b);}}
static TX_BUFFER_REQUEST* PoolGet(){std::lock_guard<std::mutex> l(g_poolLock);if(g_pool.empty())return nullptr;
 auto* b=g_pool.back();g_pool.pop_back();bool was=b->Request->inPool.exchange(false);assert(was);return b;}
static void PoolReturn(TX_BUFFER_REQUEST* b){Trace("return "+std::to_string(b->Request->id));
 bool was=b->Request->inPool.exchange(true);assert(!was&&"buffer returned twice");b->TransferLength=0;++g_returns;
 std::lock_guard<std::mutex> l(g_poolLock);g_pool.push_back(b);}
static size_t PoolFree(){std::lock_guard<std::mutex> l(g_poolLock);return g_pool.size();}
static void NotifyTransmitCompletion(NETADAPTER,TX_BUFFER_REQUEST* b){PoolReturn(b);}
static USBNCM_ADAPTER_EVENT_CALLBACKS g_adapterCallbacks{NotifyTransmitCompletion};

// One packet through the production send path, as NcmTxQueue::Advance calls it.
static NTSTATUS Send(FakeDevice* dev,size_t length=100){
 TX_BUFFER_REQUEST* b=PoolGet();if(!b)return STATUS_INSUFFICIENT_RESOURCES;
 b->TransferLength=length;NTSTATUS s;{DispatchScope d;s=UsbNcmHostDevice::TransmitFrames(dev,b);}
 Trace("transmit "+Hex(s));
 if(!NT_SUCCESS(s))PoolReturn(b);
 return s;}

struct Rig{FakeDevice dev;FakePipe pipe;UsbNcmHostDevice* host;
 Rig(){host=new UsbNcmHostDevice(&dev);dev.host=host;pipe.target.device=&dev;
  host->m_DataBulkOutPipe=&pipe;host->m_DataBulkOutPipeMaximumPacketSize=512;host->m_NcmAdapterCallbacks=&g_adapterCallbacks;}};
'''

EQUIVALENCE = r'''
// One scripted sequence; the I/O trace must match the frozen head exactly.
int main(){
 PoolInit(16);Rig rig;
#ifndef FROZEN_HEAD
 g_regHasValue=false;assert(rig.host->InitializeDataPathControl()==STATUS_SUCCESS);
 assert(rig.host->m_DataPathDebug==0&&rig.host->m_TxRecoveryWorkItem==nullptr&&g_workItemCreates==0);
#endif
 FakeTarget* t=&rig.pipe.target;
 UsbNcmHostDevice::StartTransmit(&rig.dev);
 Send(&rig.dev);Send(&rig.dev);Send(&rig.dev);
 CompleteSent(t,1,STATUS_SUCCESS,0);
 CompleteSent(t,1,STATUS_UNSUCCESSFUL,USBD_STATUS_XACT_ERROR);
 CompleteSent(t,1,STATUS_IO_TIMEOUT,USBD_STATUS_CANCELED);
 g_sendMode=SendMode::InlineSuccess;Send(&rig.dev);
 g_sendMode=SendMode::InlineXact;Send(&rig.dev);
 g_sendMode=SendMode::Reject;Send(&rig.dev);
 g_sendMode=SendMode::Pend;g_formatStatus=STATUS_INSUFFICIENT_RESOURCES;Send(&rig.dev);g_formatStatus=STATUS_SUCCESS;
 Send(&rig.dev,512);Send(&rig.dev,2048);
 CompleteSent(t,1,STATUS_NO_SUCH_DEVICE,USBD_STATUS_DEVICE_GONE);
 UsbNcmHostDevice::StopTransmit(&rig.dev);
 Send(&rig.dev);                       // queued by the stopped target
 g_startResults={STATUS_INSUFFICIENT_RESOURCES};UsbNcmHostDevice::StartTransmit(&rig.dev);
 UsbNcmHostDevice::StartTransmit(&rig.dev);
 CompleteSent(t,8,STATUS_SUCCESS,0);
 rig.host->m_DataBulkOutPipe=nullptr;Send(&rig.dev);
 UsbNcmHostDevice::StopTransmit(&rig.dev);UsbNcmHostDevice::StartTransmit(&rig.dev);
 for(auto& s:g_trace)if(s!="flush")std::printf("%s\n",s.c_str());
 std::printf("free %zu of %d\n",PoolFree(),g_poolSize);
 assert(PoolFree()==(size_t)g_poolSize);
#ifndef FROZEN_HEAD
 // Only the timeout label changed; no new message appears with switch 0.
 assert(LogsWith("TX timed out")==1&&LogsWith("OUT ")==0&&LogsWith("data-path")==0&&LogsWith("TX dropped")==0);
 assert(rig.host->m_TxInflight==0);
#endif
}
'''

MAIN = r'''
static int checks=0;
#define CHECK(e) do{++checks;if(!(e)){std::fprintf(stderr,"FAIL line %d: %s\n",__LINE__,#e);std::abort();}}while(0)
using U=UsbNcmHostDevice;
static void Reset(){std::lock_guard<std::mutex> l(g_traceLock);g_trace.clear();g_logs.clear();}
static Rig* NewRig(bool hasValue,ULONG value){
 g_regHasValue=hasValue;g_regValue=value;auto* r=new Rig;CHECK(r->host->InitializeDataPathControl()==STATUS_SUCCESS);return r;}
static bool Running(Rig* r){WdfWaitLockAcquire(r->host->m_TxLifecycleLock,nullptr);bool v=r->host->m_TxPipeRunning;WdfWaitLockRelease(r->host->m_TxLifecycleLock);return v;}
static void ExpectAllReturned(Rig* r){CHECK(PoolFree()==(size_t)g_poolSize);CHECK(r->host->m_TxInflight==0);}

static void SwitchValues(){
 struct Case{bool has;ULONG value;NTSTATUS open;ULONG expect;}cases[]={
  {false,0,STATUS_SUCCESS,0},{true,0,STATUS_SUCCESS,0},{true,1,STATUS_SUCCESS,1},{true,2,STATUS_SUCCESS,2},
  {true,3,STATUS_SUCCESS,3},{true,4,STATUS_SUCCESS,0},{true,7,STATUS_SUCCESS,0},{true,0xffffffffu,STATUS_SUCCESS,0},
  {true,3,STATUS_OBJECT_NAME_NOT_FOUND,0}};
 for(auto& c:cases){
  Reset();g_regOpenStatus=c.open;int creates=g_workItemCreates;Rig* r=NewRig(c.has,c.value);g_regOpenStatus=STATUS_SUCCESS;
  CHECK(r->host->m_DataPathDebug==c.expect);
  CHECK((r->host->m_TxRecoveryWorkItem!=nullptr)==((c.expect&2)!=0));
  CHECK(g_workItemCreates-creates==((c.expect&2)?1:0));
  CHECK(r->host->m_TxAdmissionOpen==!(c.expect&2)); // closed until a successful start
  CHECK(LogsWith("data-path debug")==(c.expect!=0)+(c.has&&c.value!=c.expect&&NT_SUCCESS(c.open)));
 }
 // A work item that cannot be created leaves diagnostics only.
 Reset();g_workItemCreateStatus=STATUS_INSUFFICIENT_RESOURCES;Rig* r=NewRig(true,3);g_workItemCreateStatus=STATUS_SUCCESS;
 CHECK(r->host->m_DataPathDebug==1&&r->host->m_TxRecoveryWorkItem==nullptr&&r->host->m_TxAdmissionOpen);
 g_waitLockCreateStatus=STATUS_INSUFFICIENT_RESOURCES;g_regHasValue=false;Rig r2;
 CHECK(r2.host->InitializeDataPathControl()==STATUS_INSUFFICIENT_RESOURCES);g_waitLockCreateStatus=STATUS_SUCCESS;
 std::puts("switch: missing/0/unknown bits -> 0; 1, 2, 3 as defined; work item only with 0x2 PASS");
}

// Values 0 and 1 never act: an XACT error queues nothing and the stopped
// target still queues sends exactly as before.
static void NoRecoveryModes(){
 for(ULONG v:{0u,1u}){
  Reset();Rig* r=NewRig(true,v);FakeTarget* t=&r->pipe.target;U::StartTransmit(&r->dev);CHECK(Running(r));
  Send(&r->dev);Send(&r->dev);CompleteSent(t,1,STATUS_UNSUCCESSFUL,USBD_STATUS_XACT_ERROR);
  CHECK(r->host->m_TxCompletionFailures==1&&r->host->m_TxRecoveryQueued==0);
  U::StopTransmit(&r->dev);CHECK(TraceCount("reset")==0);
  CHECK(NT_SUCCESS(Send(&r->dev))&&t->queued.size()==1);    // queued, as at the frozen head
  U::StartTransmit(&r->dev);CompleteSent(t,4,STATUS_SUCCESS,0);
  CHECK(LogsWith("OUT first failure")==(v==1));
  CHECK(LogsWith("OUT stop:")==(v==1));
  CHECK(LogsWith("OUT recovery")==0);
  if(v==1)CHECK(r->host->m_TxInflightPeak==2&&r->host->m_TxSuccesses==1&&r->host->m_TxLastSuccessTime!=0);
  else CHECK(r->host->m_TxInflightPeak==0&&r->host->m_TxSuccesses==0);
  U::StopTransmit(&r->dev);ExpectAllReturned(r);
 }
 std::puts("switch 0/1: no recovery, stopped target still queues, instrumentation only with 0x1 PASS");
}

static void Classification(){
 struct Case{NTSTATUS s;USBD_STATUS u;}none[]={
  {STATUS_CANCELLED,USBD_STATUS_CANCELED},{STATUS_IO_TIMEOUT,USBD_STATUS_CANCELED},
  {STATUS_NO_SUCH_DEVICE,USBD_STATUS_XACT_ERROR},{STATUS_DEVICE_NOT_CONNECTED,USBD_STATUS_XACT_ERROR},
  {STATUS_DEVICE_REMOVED,USBD_STATUS_XACT_ERROR},{STATUS_DELETE_PENDING,USBD_STATUS_XACT_ERROR},
  {STATUS_DEVICE_DOES_NOT_EXIST,USBD_STATUS_XACT_ERROR},{STATUS_DEVICE_POWERED_OFF,USBD_STATUS_XACT_ERROR},
  {STATUS_UNSUCCESSFUL,USBD_STATUS_DEVICE_GONE},{STATUS_UNSUCCESSFUL,USBD_STATUS_STALL_PID},
  {STATUS_UNSUCCESSFUL,USBD_STATUS_BABBLE_DETECTED},{STATUS_IO_DEVICE_ERROR,0},{STATUS_UNSUCCESSFUL,0}};
 for(auto& c:none){
  Reset();Rig* r=NewRig(true,3);U::StartTransmit(&r->dev);Send(&r->dev);
  CompleteSent(&r->pipe.target,1,c.s,c.u);
  CHECK(Enqueues(r->host->m_TxRecoveryWorkItem)==0);
  CHECK(LogsWith("TX cancelled")+LogsWith("TX timed out")+LogsWith("TX completion failed")==1); // still reported
  U::StopTransmit(&r->dev);ExpectAllReturned(r);
 }
 Reset();Rig* r=NewRig(true,3);U::StartTransmit(&r->dev);Send(&r->dev);
 CompleteSent(&r->pipe.target,1,STATUS_UNSUCCESSFUL,USBD_STATUS_XACT_ERROR);
 CHECK(Enqueues(r->host->m_TxRecoveryWorkItem)==1&&LogsWith("TX completion failed")==1);
 U::StopTransmit(&r->dev);ExpectAllReturned(r);
 std::puts("trigger: only a live-device USBD_STATUS_XACT_ERROR; cancel, timeout, removal statuses and other errors only reported PASS");
}

static void RecoveryCycle(ULONG v){
 Reset();Rig* r=NewRig(true,v);FakeTarget* t=&r->pipe.target;auto* w=r->host->m_TxRecoveryWorkItem;
 int before=g_sendCalls;
 CHECK(Send(&r->dev)==STATUS_DEVICE_NOT_READY&&g_sendCalls==before);   // not started: closed, not queued
 U::StartTransmit(&r->dev);
 for(int i=0;i<5;++i)Send(&r->dev);
 CompleteSent(t,1,STATUS_UNSUCCESSFUL,USBD_STATUS_XACT_ERROR);
 CompleteSent(t,1,STATUS_UNSUCCESSFUL,USBD_STATUS_XACT_ERROR);       // coalesced
 CHECK(Enqueues(w)==1&&r->host->m_TxRecoveryCoalesced==1);
 int sends=g_sendCalls;
 CHECK(RunQueuedWorkItem(w));
 CHECK(TraceCount("stop")==1&&TraceCount("reset")==1&&TraceCount("start 00000000")==2);
 CHECK(SentCount(t)==0&&r->host->m_TxCancellations==3);             // three pending were cancelled
 CHECK(Running(r)&&r->host->m_TxAdmissionOpen&&r->host->m_TxRecoveryQueued==0);
 CHECK(r->host->m_TxRecoveryAttempts==1);
 CHECK(LogsWith("OUT recovery %lu/%u start")==1&&LogsWith("drain %I64u ms")==1);
 CHECK(g_sendCalls==sends);                                          // no payload retried
 CHECK(NT_SUCCESS(Send(&r->dev))&&SentCount(t)==1);                   // fresh traffic flows
 CompleteSent(t,1,STATUS_SUCCESS,0);
 CHECK(LogsWith("OUT first failure")==(v&1)&&LogsWith("OUT stop:")==0);
 U::StopTransmit(&r->dev);CHECK(LogsWith("OUT stop:")==(v&1));ExpectAllReturned(r);
 std::printf("switch %u: one XACT error -> drain, stop, reset, start, reopen; coalesced duplicate PASS\n",v);
}

static void FailedResetAndStart(){
 // Reset fails: never started, never reopened; sends are refused, not queued.
 Reset();Rig* r=NewRig(true,2);FakeTarget* t=&r->pipe.target;U::StartTransmit(&r->dev);Send(&r->dev);
 g_resetResult=STATUS_IO_TIMEOUT;CompleteSent(t,1,STATUS_UNSUCCESSFUL,USBD_STATUS_XACT_ERROR);
 CHECK(RunQueuedWorkItem(r->host->m_TxRecoveryWorkItem));g_resetResult=STATUS_SUCCESS;
 CHECK(TraceCount("start")==1&&!Running(r)&&!r->host->m_TxAdmissionOpen&&LogsWith("OUT recovery %lu/%u %s")==1);
 int sends=g_sendCalls;CHECK(Send(&r->dev)==STATUS_DEVICE_NOT_READY&&g_sendCalls==sends&&t->queued.empty());
 CHECK(r->host->m_TxAdmissionRejects==1);
 U::StopTransmit(&r->dev);U::StartTransmit(&r->dev);                 // normal queue restart reopens
 CHECK(Running(r)&&NT_SUCCESS(Send(&r->dev)));CompleteSent(t,1,STATUS_SUCCESS,0);
 U::StopTransmit(&r->dev);ExpectAllReturned(r);
 // Start after a good reset fails: same, the failure is kept.
 Reset();r=NewRig(true,2);t=&r->pipe.target;U::StartTransmit(&r->dev);Send(&r->dev);
 CompleteSent(t,1,STATUS_UNSUCCESSFUL,USBD_STATUS_XACT_ERROR);
 g_startResults={STATUS_INSUFFICIENT_RESOURCES};CHECK(RunQueuedWorkItem(r->host->m_TxRecoveryWorkItem));
 CHECK(TraceCount("reset")==1&&!Running(r)&&!r->host->m_TxAdmissionOpen);
 CHECK(Send(&r->dev)==STATUS_DEVICE_NOT_READY);
 // A queue start whose pipe start fails is not marked running either.
 U::StopTransmit(&r->dev);g_startResults={STATUS_INSUFFICIENT_RESOURCES};U::StartTransmit(&r->dev);
 CHECK(!Running(r)&&!r->host->m_TxAdmissionOpen&&Send(&r->dev)==STATUS_DEVICE_NOT_READY);
 CHECK(LogsWith("OUT pipe start failed")==1);
 U::StopTransmit(&r->dev);ExpectAllReturned(r);
 std::puts("failed reset or start: not running, admission stays closed, nothing queued, queue restart reopens PASS");
}

static void Trigger(Rig* r){Send(&r->dev);CompleteSent(&r->pipe.target,1,STATUS_UNSUCCESSFUL,USBD_STATUS_XACT_ERROR);RunQueuedWorkItem(r->host->m_TxRecoveryWorkItem);}
static void Budget(){
 Reset();Rig* r=NewRig(true,2);U::StartTransmit(&r->dev);r->host->BeginD0Session();
 Trigger(r);CHECK(r->host->m_TxRecoveryAttempts==1);
 AdvanceSeconds(5);Trigger(r);                                        // inside the cooldown
 CHECK(r->host->m_TxRecoveryAttempts==1&&TraceCount("reset")==1&&LogsWith("OUT recovery skipped")==1);
 CHECK(Running(r)&&r->host->m_TxRecoveryQueued==0);
 AdvanceSeconds(6);Trigger(r);CHECK(r->host->m_TxRecoveryAttempts==2);
 AdvanceSeconds(11);Trigger(r);CHECK(r->host->m_TxRecoveryAttempts==3);
 AdvanceSeconds(11);Trigger(r);CHECK(r->host->m_TxRecoveryAttempts==3&&TraceCount("reset")==3);
 CHECK(r->host->m_TxRecoverySkipped==2);
 // Queue stop/start inside the D0 session does not replenish the budget.
 U::StopTransmit(&r->dev);U::StartTransmit(&r->dev);AdvanceSeconds(11);Trigger(r);
 CHECK(r->host->m_TxRecoveryAttempts==3&&TraceCount("reset")==3&&r->host->m_TxRecoverySkipped==3);
 // A new D0 session does.
 U::StopTransmit(&r->dev);r->host->BeginD0Session();U::StartTransmit(&r->dev);Trigger(r);
 CHECK(r->host->m_TxRecoveryAttempts==1&&TraceCount("reset")==4);
 U::StopTransmit(&r->dev);ExpectAllReturned(r);
 std::puts("budget: 10 s cooldown skip logged, 3 per D0 session, queue restart does not replenish PASS");
}

// The lifecycle wins over a queued work item: it never touches the pipe.
static void StopAndRemovalRaces(){
 for(int path=0;path<2;++path){
  Reset();Rig* r=NewRig(true,3);auto* w=r->host->m_TxRecoveryWorkItem;U::StartTransmit(&r->dev);
  Send(&r->dev);Send(&r->dev);CompleteSent(&r->pipe.target,1,STATUS_UNSUCCESSFUL,USBD_STATUS_XACT_ERROR);
  CHECK(Enqueues(w)==1);
  if(path==0)U::StopTransmit(&r->dev);else CHECK(r->host->LeaveWorkingState()==STATUS_SUCCESS);
  CHECK(TraceCount("stop")==1&&TraceCount("reset")==0&&LogsWith("OUT recovery skipped")==1);
  CHECK(r->host->m_TxRecoveryQueued==0&&!RunQueuedWorkItem(w));
  r->pipe.valid=false;                    // SelectSetting on the next D0Entry drops the pipe
  int enq=Enqueues(w);CHECK(Send(&r->dev)==STATUS_DEVICE_NOT_READY&&Enqueues(w)==enq);
  CHECK(r->pipe.target.sendsWhileStopped==0);ExpectAllReturned(r);
 }
 // Partial initialization: no pipe at all.
 Reset();Rig* r=NewRig(true,3);r->host->m_DataBulkOutPipe=nullptr;r->pipe.valid=false;
 U::StartTransmit(&r->dev);CHECK(!Running(r)&&Send(&r->dev)==STATUS_DEVICE_NOT_READY);
 r->host->RequestOutPipeRecovery(STATUS_UNSUCCESSFUL,USBD_STATUS_XACT_ERROR);
 U::StopTransmit(&r->dev);CHECK(LogsWith("OUT recovery skipped")==1&&r->host->m_TxRecoveryQueued==0);
 CHECK(r->host->LeaveWorkingState()==STATUS_SUCCESS);ExpectAllReturned(r);
 std::puts("stop/D0Exit/null pipe: queued work item skips, flush outside lock, no late enqueue, no stale pipe PASS");
}

static void InlineCompletion(){
 Reset();Rig* r=NewRig(true,3);U::StartTransmit(&r->dev);
 g_sendMode=SendMode::InlineXact;CHECK(Send(&r->dev)==STATUS_SUCCESS);g_sendMode=SendMode::Pend;
 CHECK(g_returns.load()>0&&Enqueues(r->host->m_TxRecoveryWorkItem)==1&&r->host->m_TxInflight==0);
 CHECK(TraceCount("getstatus")==0);                                   // request not read after the send
 g_sendMode=SendMode::InlineSuccess;CHECK(Send(&r->dev)==STATUS_SUCCESS);g_sendMode=SendMode::Pend;
 g_sendMode=SendMode::Reject;CHECK(Send(&r->dev)==STATUS_INVALID_DEVICE_STATE);g_sendMode=SendMode::Pend;
 g_formatStatus=STATUS_INSUFFICIENT_RESOURCES;CHECK(Send(&r->dev)==STATUS_INSUFFICIENT_RESOURCES);g_formatStatus=STATUS_SUCCESS;
 CHECK(r->host->m_TxInflight==0&&r->host->m_TxSendFailures==2);
 CHECK(RunQueuedWorkItem(r->host->m_TxRecoveryWorkItem)&&Running(r));
 U::StopTransmit(&r->dev);ExpectAllReturned(r);
 std::puts("ownership: inline completion, send=FALSE and format failure each return the buffer once PASS");
}

// A sender inside its section holds off the stop; a sender arriving after
// admission closed is refused without reaching the target; none during reset.
static void AdmissionRace(){
 Reset();Rig* r=NewRig(true,2);FakeTarget* t=&r->pipe.target;auto* w=r->host->m_TxRecoveryWorkItem;U::StartTransmit(&r->dev);
 Send(&r->dev);CompleteSent(t,1,STATUS_UNSUCCESSFUL,USBD_STATUS_XACT_ERROR);CHECK(Enqueues(w)==1);
 std::thread worker;std::atomic<bool> lateRefused{false};
 g_sendHook=[&]{
  worker=std::thread([&]{RunQueuedWorkItem(w);});
  while(!GateClosing(&r->host->m_TxAdmission))std::this_thread::yield();
  std::thread late([&]{lateRefused=Send(&r->dev)==STATUS_DEVICE_NOT_READY;});late.join();
  std::this_thread::sleep_for(std::chrono::milliseconds(50));
  CHECK(TraceCount("stop")==0);                                       // still waiting for this section
  Trace("section-exit");
 };
 g_sendHookArmed=true;Send(&r->dev);worker.join();
 CHECK(lateRefused.load());
 int exitAt=-1,stopAt=-1;{std::lock_guard<std::mutex> l(g_traceLock);for(int i=0;i<(int)g_trace.size();++i){if(g_trace[i]=="section-exit")exitAt=i;if(g_trace[i]=="stop")stopAt=i;}}
 CHECK(exitAt>=0&&stopAt>exitAt);
 std::atomic<int> duringReset{0};
 AdvanceSeconds(11);                     // the section's own request was cancelled by that stop
 Send(&r->dev);CompleteSent(t,1,STATUS_UNSUCCESSFUL,USBD_STATUS_XACT_ERROR);
 g_resetHook=[&]{std::thread p([&]{duringReset=Send(&r->dev);});p.join();};
 RunQueuedWorkItem(w);g_resetHook=nullptr;
 CHECK(duringReset.load()==STATUS_DEVICE_NOT_READY&&t->sendsDuringReset==0&&t->sendsWhileStopped==0);
 U::StopTransmit(&r->dev);ExpectAllReturned(r);
 std::puts("admission: active section drains before stop; late and during-reset sends refused PASS");
}

static void Stress(){
 Reset();Rig* r=NewRig(true,3);FakeTarget* t=&r->pipe.target;auto* w=r->host->m_TxRecoveryWorkItem;
 r->host->BeginD0Session();U::StartTransmit(&r->dev);
 std::atomic<bool> stop{false};std::vector<std::thread> threads;
 for(int p=0;p<4;++p)threads.emplace_back([&,p]{std::mt19937 rng(p);
  while(!stop){unsigned k=rng()%10;
   if(k==0)g_sendMode=SendMode::InlineXact;else if(k==1)g_sendMode=SendMode::InlineSuccess;else g_sendMode=SendMode::Pend;
   Send(&r->dev);std::this_thread::yield();}});
 threads.emplace_back([&]{std::mt19937 rng(9);while(!stop){unsigned k=rng()%8;
  CompleteSent(t,1,k==0?STATUS_UNSUCCESSFUL:k==1?STATUS_IO_TIMEOUT:STATUS_SUCCESS,k==0?USBD_STATUS_XACT_ERROR:0);std::this_thread::yield();}});
 threads.emplace_back([&]{while(!stop){if(!RunQueuedWorkItem(w))std::this_thread::yield();}});
 for(int cycle=0;cycle<40;++cycle){
  std::this_thread::sleep_for(std::chrono::milliseconds(5));AdvanceSeconds(11);
  if(cycle%10==9){U::StopTransmit(&r->dev);r->host->BeginD0Session();U::StartTransmit(&r->dev);}
 }
 stop=true;for(auto& th:threads)th.join();g_sendMode=SendMode::Pend;
 U::StopTransmit(&r->dev);
 int enq=Enqueues(w);CompleteSent(t,1000,STATUS_SUCCESS,0);
 CHECK(Enqueues(w)==enq&&!RunQueuedWorkItem(w));
 CHECK(t->sendsDuringReset==0&&t->sendsWhileStopped==0&&t->queued.empty());
 ExpectAllReturned(r);
 CHECK(TraceCount("reset")>0);
 std::printf("stress: %d sends, %d resets, %ld refused, every buffer returned once PASS\n",
             g_sendCalls.load(),TraceCount("reset"),(long)r->host->m_TxAdmissionRejects);
}

int main(){
 PoolInit(32);
 SwitchValues();NoRecoveryModes();Classification();
 RecoveryCycle(2);RecoveryCycle(3);FailedResetAndStart();Budget();
 StopAndRemovalRaces();InlineCompletion();AdmissionRace();Stress();
 std::printf("OUT recovery probe: %d checks, 0 failures\n",checks);
}
'''


def build(tmp, name, header, functions, body, defines=()):
    cpp = Path(tmp)/(name + '.cpp')
    source = '#define private public\n' + class_text(header) + COMMON + functions + body
    cpp.write_text(SHIM + '#include "' + str(DRIVER/'host/out_pipe_policy.h') + '"\n' + source)
    binary = Path(tmp)/name
    subprocess.run(['clang++', '-std=c++17', '-fsanitize=address,undefined', '-pthread', '-g', '-O1',
                    *defines, str(cpp), '-o', str(binary)], check=True)
    return binary


def main():
    device = (DRIVER/'host/device.cpp').read_text()
    header = (DRIVER/'host/device.h').read_text()
    for forbidden in ('ResetPortSynchronously', 'CyclePortSynchronously', 'WdfUsbTargetDeviceReset'):
        assert forbidden not in device, forbidden + ' must not be used'
    current = '\n'.join(extract(device, s) for s in NEW_FUNCTIONS)
    old_device = frozen('NCM-Driver-for-Windows/host/device.cpp')
    old = '\n'.join(extract(old_device, s) for s in TX_FUNCTIONS)
    with tempfile.TemporaryDirectory(prefix='sideline-out-recovery-') as tmp:
        baseline = build(tmp, 'frozen', frozen('NCM-Driver-for-Windows/host/device.h'), old,
                         EQUIVALENCE, ['-DFROZEN_HEAD'])
        switch0 = build(tmp, 'switch0', header, current, EQUIVALENCE)
        # Test objects are leaked on purpose; leak reports are not the subject.
        env = dict(os.environ, ASAN_OPTIONS='detect_leaks=0')
        expected = subprocess.run([str(baseline)], check=True, capture_output=True, text=True, env=env).stdout
        actual = subprocess.run([str(switch0)], check=True, capture_output=True, text=True, env=env).stdout
        if expected != actual:
            print('switch 0 I/O trace differs from frozen head', FROZEN[:12])
            print('--- frozen\n' + expected + '--- switch 0\n' + actual)
            return 1
        print(f'switch 0: I/O trace identical to frozen {FROZEN[:12]} '
              f'({len(expected.splitlines())} events) PASS')
        probe = build(tmp, 'probe', header, current, MAIN)
        return subprocess.run([str(probe)], timeout=60, env=env).returncode


if __name__ == '__main__':
    sys.exit(main())
