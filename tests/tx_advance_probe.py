"""Actual TX Advance control flow with OS/pool/NTB shims, not kernel qualification."""
from pathlib import Path
import subprocess
import tempfile
import sys
from rx_completion_probe import function_from_source, root

advance=function_from_source(root/'adapter/txqueue.cpp','void\nNcmTxQueue::Advance(')
cancel=function_from_source(root/'adapter/txqueue.cpp','void\nNcmTxQueue::Cancel(')
shim=r'''
#include <cassert>
#include <cstdio>
#include <vector>
#include <cstddef>
using NTSTATUS=int;
constexpr int STATUS_SUCCESS=0,STATUS_BUFFER_TOO_SMALL=-1;
#define NT_SUCCESS(x) ((x)>=0)
enum {NTB_TX};
struct ETHERNET_HEADER{unsigned char bytes[14];};
struct Packet{bool Ignore=false;size_t bytes=64;bool unfit=false;};
struct NET_RING{unsigned BeginIndex,EndIndex;};
struct NET_RING_COLLECTION{NET_RING* packets;NET_RING* fragments;};
static NET_RING* NetRingCollectionGetPacketRing(const NET_RING_COLLECTION* c){return c->packets;}
static NET_RING* NetRingCollectionGetFragmentRing(const NET_RING_COLLECTION* c){return c->fragments;}
struct NcmOsQueue{std::vector<Packet> packets;size_t begin=0;int sets=0,reads=0;const NET_RING_COLLECTION* RingCollection=nullptr;};
struct NcmPacketIterator{
 NcmOsQueue* q;size_t i;
 bool HasAny(){return i<q->packets.size();}
 Packet* GetPacket(){assert(HasAny());return &q->packets[i];}
 void Advance(){++i;}void Set(){q->begin=i;++q->sets;}
};
static NcmPacketIterator NcmGetAllPackets(NcmOsQueue* q){return {q,q->begin};}
static size_t NcmGetPacketDataLength(NcmPacketIterator* pi){
 assert(!pi->GetPacket()->Ignore);++pi->q->reads;return pi->GetPacket()->bytes;
}
struct TX_BUFFER_REQUEST{unsigned char Buffer[512]{};size_t BufferLength=512,TransferLength=0;};
struct Pool{TX_BUFFER_REQUEST request;bool available=true;int gets=0,returns=0;};
static int TxBufferRequestPoolGetBufferRequest(Pool* p,TX_BUFFER_REQUEST** r){
 ++p->gets;if(!p->available)return -1;*r=&p->request;return 0;
}
static void TxBufferRequestPoolReturnBufferRequest(Pool* p,TX_BUFFER_REQUEST*){++p->returns;}
struct Ntb{int datagrams=0;size_t max=2;int setCalls=0;};
static int NcmTransferBlockReInitializeBuffer(Ntb* n,unsigned char*,size_t,int){n->datagrams=0;return 0;}
static int NcmTransferBlockCopyNextDatagram(Ntb* n,NcmPacketIterator* pi){
 assert(!pi->GetPacket()->Ignore);
 if(pi->GetPacket()->unfit||size_t(n->datagrams)>=n->max)return STATUS_BUFFER_TOO_SMALL;
 ++n->datagrams;return 0;
}
static void NcmTransferBlockSetNdp(Ntb* n,size_t* length){
 assert(n->datagrams>0);++n->setCalls;*length=64*n->datagrams;
}
struct Adapter{
 struct{size_t MaxDatagramSize=1514;}m_Parameters;
 struct Callbacks{int sends=0;bool fail=false;int EvtUsbNcmTransmitFrames(void*,TX_BUFFER_REQUEST* r){assert(r->TransferLength>0);++sends;return fail?-1:0;}}callbacks;
 Callbacks* m_UsbNcmDeviceCallbacks=&callbacks;void* GetWdfDevice(){return nullptr;}
};
struct NcmTxQueue{NcmOsQueue m_OsQueue;Pool* m_TxBufferRequestPool;Ntb* m_NtbHandle;Adapter* m_NcmAdapter;void Advance();void Cancel();};
'''
main=r'''
int main(){
 int checks=0;
 auto run=[&](std::vector<Packet> packets,int sends,int returned,bool available=true,bool sendFail=false){
  Pool pool;pool.available=available;Ntb ntb;Adapter adapter;adapter.callbacks.fail=sendFail;
  NcmTxQueue q{{packets},&pool,&ntb,&adapter};q.Advance();
  assert(q.m_OsQueue.begin==packets.size());assert(adapter.callbacks.sends==sends);
  assert(pool.returns==returned);assert(ntb.setCalls==sends);++checks;
 };
 run({},0,0);
 run({{true,64,false}},0,0);
 run({{true,64,false},{true,64,false}},0,0);
 run({{true,64,false},{false,64,false}},1,0);
 run({{false,64,false},{true,64,false},{false,64,false}},1,0);
 run({{false,0,false},{false,13,false},{false,1515,false}},0,1);
 run({{false,64,true}},0,1);
 run({{false,64,true},{false,64,false}},1,0);
 run({{false,64,false},{false,64,false},{false,64,false}},2,0);
 run({{false,64,false}},0,0,false);
 run({{false,64,false}},1,1,true,true);
 for(bool empty:{false,true})for(bool ignored:{false,true}){
  NET_RING p{empty?4u:1u,4},f{empty?7u:2u,7};NET_RING_COLLECTION c{&p,&f};
  Pool pool;Ntb ntb;Adapter adapter;NcmTxQueue q{{{{ignored,64,false}}},&pool,&ntb,&adapter};
  q.m_OsQueue.RingCollection=&c;q.Cancel();
  assert(p.BeginIndex==p.EndIndex&&f.BeginIndex==f.EndIndex);
  assert(q.m_OsQueue.packets[0].Ignore==ignored);q.Cancel();++checks;
 }
 std::printf("TX ignored/invalid/unfit/flush/pool/send failure/cancel: %d checks, 0 failures\n",checks);
}
'''
def run_probe():
    with tempfile.TemporaryDirectory(prefix='sideline-ncm-txadvance-') as tmp:
        cpp=Path(tmp)/'probe.cpp';cpp.write_text(shim+advance+cancel+main)
        binary=Path(tmp)/'probe'
        subprocess.run(['clang++','-std=c++17','-fsanitize=address,undefined','-g',str(cpp),'-o',str(binary)],check=True)
        return subprocess.run([str(binary)]).returncode
if __name__=='__main__':sys.exit(run_probe())
