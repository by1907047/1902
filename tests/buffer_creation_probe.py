"""Fault-inject external allocation calls in the real RX/TX pool creators.

Portable ownership/status tests, not real WDF/DMF cleanup or kernel tests.
The production break caught is ignoring a failed allocation and publishing an
incomplete pool, or failing to return the checked-out node on partial failure.
"""
from pathlib import Path
import subprocess
import sys
import tempfile

from rx_completion_probe import function_from_source, root

header = (root / 'inc/buffers.h').read_text()
structures = header[header.index('struct RX_BUFFER'):header.index('\nPAGED\n')]
functions = '\n'.join([
    function_from_source(root / 'common/buffers.cpp', 'NTSTATUS\nTxBufferRequestPoolCreate('),
    function_from_source(root / 'common/buffers.cpp', 'NTSTATUS\nRxBufferQueueCreate('),
])
shim = r'''
#include <cstdint>
#include <cstddef>
#include <cstdio>
#include <cstring>
#include <cassert>
#include <memory>
#include <vector>
#define _Out_
#define NT_SUCCESS(s) ((s)>=0)
#define NCM_LOG_IF_NOT_NT_SUCCESS_MSG(expr,msg) do { (void)(expr); } while(0)
#define NCM_RETURN_IF_NOT_NT_SUCCESS_MSG(expr,msg) do { auto s=(expr); if(!NT_SUCCESS(s)) return s; } while(0)
#define PAGED_CODE() ((void)0)
using NTSTATUS=int; using ULONG=uint32_t; using UCHAR=uint8_t;
using PUCHAR=uint8_t*; using PVOID=void*; using HANDLE=void*;
using WDFDEVICE=void*; using WDFOBJECT=void*; using WDFREQUEST=void*;
using WDFMEMORY=void*; using DMFMODULE=void*;
using TX_BUFFER_REQUEST_POOL=void*; using RX_BUFFER_QUEUE=void*;
struct NDIS_STATISTICS_INFO { uint64_t dummy[8]; };
constexpr int STATUS_SUCCESS=0, STATUS_UNSUCCESSFUL=-1, STATUS_INSUFFICIENT_RESOURCES=-4;
constexpr bool FALSE=false, TRUE=true;
constexpr int NonPagedPoolNx=0;
struct WDF_OBJECT_ATTRIBUTES { WDFOBJECT ParentObject; };
#define WDF_OBJECT_ATTRIBUTES_INIT(a) ((a)->ParentObject=nullptr)
struct DMF_MODULE_ATTRIBUTES {};
struct DMF_CONFIG_BufferQueue {
  struct {
    size_t BufferContextSize,BufferSize,BufferCount;
    bool CreateWithTimer,EnableLookAside; int PoolType;
  } SourceSettings;
};
#define DMF_CONFIG_BufferQueue_AND_ATTRIBUTES_INIT(c,a) do { *(c)={}; *(a)={}; } while(0)
struct Object { bool live=true; virtual ~Object()=default; };
struct Node { std::unique_ptr<uint8_t[]> bytes; bool fetched=false,queued=false; };
struct Module: Object { std::vector<Node> nodes; std::vector<std::unique_ptr<Object>> children; bool tx; };
static std::vector<std::unique_ptr<Module>> modules;
static int failStage=0, failAt=1, memoryCalls=0,requestCalls=0,fetchCalls=0,invalidUses=0,invalidEnqueues=0,unreturnedNodes=0;
static bool Fail(int stage,int call) { return failStage==stage && call==failAt; }
'''
mocks = r'''
static NTSTATUS DMF_BufferQueue_Create(WDFDEVICE,DMF_MODULE_ATTRIBUTES*,WDF_OBJECT_ATTRIBUTES*,
                                      DMFMODULE* out);
// Overload includes configuration through the initializer's documented settings.
static DMF_CONFIG_BufferQueue* currentConfig=nullptr;
#undef DMF_CONFIG_BufferQueue_AND_ATTRIBUTES_INIT
#define DMF_CONFIG_BufferQueue_AND_ATTRIBUTES_INIT(c,a) do { *(c)={}; *(a)={}; currentConfig=(c); } while(0)
static NTSTATUS DMF_BufferQueue_Create(WDFDEVICE,DMF_MODULE_ATTRIBUTES*,WDF_OBJECT_ATTRIBUTES*,DMFMODULE* out) {
  if(Fail(1,1)) { *out=nullptr; return STATUS_INSUFFICIENT_RESOURCES; }
  auto m=std::make_unique<Module>(); m->tx=currentConfig->SourceSettings.BufferSize!=sizeof(RX_BUFFER);
  for(size_t i=0;i<currentConfig->SourceSettings.BufferCount;++i) {
    Node n; n.bytes=std::make_unique<uint8_t[]>(currentConfig->SourceSettings.BufferSize);
    m->nodes.push_back(std::move(n));
  }
  *out=m.get(); modules.push_back(std::move(m)); return STATUS_SUCCESS;
}
static Module* Checked(DMFMODULE h) {
  auto* m=static_cast<Module*>(h);
  if(!m || !m->live) { ++invalidUses; return nullptr; }
  return m;
}
static Node* Find(Module* m,void* p) {
  for(auto& n:m->nodes) if(n.bytes.get()==p) return &n;
  assert(false); return nullptr;
}
static NTSTATUS DMF_BufferQueue_Fetch(DMFMODULE h,PVOID* out,PVOID*) {
  auto* m=Checked(h); if(!m) return STATUS_UNSUCCESSFUL;
  if(Fail(4,++fetchCalls)) return STATUS_INSUFFICIENT_RESOURCES;
  for(auto& n:m->nodes) if(!n.fetched && !n.queued) {
    n.fetched=true; *out=n.bytes.get(); return STATUS_SUCCESS;
  }
  return STATUS_UNSUCCESSFUL;
}
static void DMF_BufferQueue_Enqueue(DMFMODULE h,void* p) {
  auto* m=Checked(h); if(!m) return;
  auto* n=Find(m,p); assert(n->fetched); n->fetched=false; n->queued=true;
  auto* tx=static_cast<TX_BUFFER_REQUEST*>(p);
  if(m->tx && (!tx->Request || !tx->BufferWdfMemory)) ++invalidEnqueues;
}
static void DMF_BufferQueue_Reuse(DMFMODULE h,void* p) {
  auto* m=Checked(h); if(!m) return;
  auto* n=Find(m,p); assert(n->fetched); n->fetched=false;
}
static NTSTATUS MakeChild(WDF_OBJECT_ATTRIBUTES* a,void** out,int stage,int call) {
  if(Fail(stage,call)) { *out=nullptr; return STATUS_INSUFFICIENT_RESOURCES; }
  auto* m=Checked(a->ParentObject); if(!m) return STATUS_UNSUCCESSFUL;
  auto child=std::make_unique<Object>(); *out=child.get(); m->children.push_back(std::move(child));
  return STATUS_SUCCESS;
}
static NTSTATUS WdfMemoryCreatePreallocated(WDF_OBJECT_ATTRIBUTES* a,void*,size_t,WDFMEMORY* out) {
  return MakeChild(a,out,2,++memoryCalls);
}
static NTSTATUS WdfRequestCreate(WDF_OBJECT_ATTRIBUTES* a,void*,WDFREQUEST* out) {
  return MakeChild(a,out,3,++requestCalls);
}
static void WdfObjectDelete(DMFMODULE h) {
  auto* m=Checked(h); if(!m) return;
  for(const auto& n:m->nodes) if(n.fetched) ++unreturnedNodes;
  for(auto& child:m->children) child->live=false;
  m->live=false;
}
static size_t LiveObjects() {
  size_t live=0; for(const auto& m:modules) {
    live+=m->live; for(const auto& child:m->children) live+=child->live;
  }
  return live;
}
static void Reset(int stage,int at) {
  modules.clear(); failStage=stage; failAt=at;
  memoryCalls=requestCalls=fetchCalls=invalidUses=invalidEnqueues=unreturnedNodes=0;
}
'''
main = r'''
int main() {
  int failures=0,checks=0;
  for(int stage=1;stage<=4;++stage) for(int at:{1,2,128}) {
    if(stage==1 && at!=1) continue;
    Reset(stage,at); TX_BUFFER_REQUEST_POOL handle=reinterpret_cast<void*>(uintptr_t(1));
    auto status=TxBufferRequestPoolCreate(nullptr,nullptr,128,&handle);
    const bool clean=status==STATUS_INSUFFICIENT_RESOURCES && handle==nullptr &&
      invalidUses==0 && invalidEnqueues==0 && LiveObjects()==0 && unreturnedNodes==0;
    ++checks; failures+=!clean;
    std::printf("TX failure stage=%d call=%d status=%d handle-null=%d invalid-use=%d invalid-enqueue=%d live=%zu checked-out-at-delete=%d %s\n",
      stage,at,status,handle==nullptr,invalidUses,invalidEnqueues,LiveObjects(),unreturnedNodes,clean?"PASS":"FAIL");
  }
  Reset(1,1); RX_BUFFER_QUEUE rx=reinterpret_cast<void*>(uintptr_t(1));
  auto status=RxBufferQueueCreate(nullptr,nullptr,&rx);
  bool clean=status==STATUS_INSUFFICIENT_RESOURCES && rx==nullptr && LiveObjects()==0;
  ++checks; failures+=!clean;
  std::printf("RX module-create failure status=%d handle-null=%d %s\n",status,rx==nullptr,clean?"PASS":"FAIL");
  Reset(0,1); TX_BUFFER_REQUEST_POOL tx=nullptr;
  status=TxBufferRequestPoolCreate(nullptr,nullptr,128,&tx);
  clean=status==STATUS_SUCCESS && tx!=nullptr && invalidUses==0 && invalidEnqueues==0;
  if(tx) { auto* m=Checked(tx); assert(m); size_t queued=0; for(const auto& n:m->nodes) queued+=n.queued;
    clean=clean && queued==128 && memoryCalls==128 && requestCalls==128;
    WdfObjectDelete(tx); clean=clean && LiveObjects()==0 && unreturnedNodes==0;
  }
  ++checks; failures+=!clean;
  std::printf("TX success creates128 complete entries %s\n",clean?"PASS":"FAIL");
  Reset(0,1); rx=nullptr; status=RxBufferQueueCreate(nullptr,nullptr,&rx);
  clean=status==STATUS_SUCCESS && rx!=nullptr && invalidUses==0;
  if(rx) { WdfObjectDelete(rx); clean=clean && LiveObjects()==0; }
  ++checks; failures+=!clean;
  std::printf("RX success %s; %d checks, %d failures\n",clean?"PASS":"FAIL",checks,failures);
  return failures!=0;
}
'''


def run_probe():
    with tempfile.TemporaryDirectory(prefix='sideline-ncm-create-') as tmp:
        cpp = Path(tmp) / 'probe.cpp'
        cpp.write_text(shim + structures + mocks + functions + main)
        binary = Path(tmp) / 'probe'
        subprocess.run(['clang++', '-std=c++17', '-fsanitize=address,undefined',
                        '-g', str(cpp), '-o', str(binary)], check=True)
        return subprocess.run([str(binary)]).returncode


if __name__ == '__main__':
    sys.exit(run_probe())
