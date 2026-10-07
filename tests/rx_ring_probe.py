"""Exercise actual RX Advance ring availability and destination capacity.

Real production Advance, synthetic OS rings/GetNextFrame only. Not a kernel
ring scheduling or device traffic test. Sanitizers cover actual copy extent.
"""
from pathlib import Path
import subprocess
import tempfile
import sys
from rx_completion_probe import function_from_source, root

function=function_from_source(root/'adapter/rxqueue.cpp','void\nNcmRxQueue::Advance(')
shim=r'''
#include <cassert>
#include <cstdio>
#include <vector>
#include <cstring>
#include <cstdint>
#include <algorithm>
using PUCHAR=unsigned char*;using UINT32=uint32_t;
constexpr int STATUS_SUCCESS=0,STATUS_NO_MORE_ENTRIES=-2;
#define NT_FRE_ASSERT(x) assert(x)
#define RtlCopyMemory(d,s,n) std::memcpy(d,s,n)
struct NET_FRAGMENT{size_t Capacity,Offset=0,ValidLength=0;};
struct NET_PACKET{UINT32 FragmentIndex=0,FragmentCount=0;struct{int dummy=0;}Layout;};
struct NET_FRAGMENT_VIRTUAL_ADDRESS{void* VirtualAddress;};
struct NcmOsQueue{
 std::vector<NET_FRAGMENT> fragments;std::vector<NET_FRAGMENT_VIRTUAL_ADDRESS> addresses;
 std::vector<NET_PACKET> packets;size_t packetBegin=0,fragmentBegin=0;
};
struct NcmPacketIterator{
 NcmOsQueue* q;size_t i;
 bool HasAny(){return i<q->packets.size();}
 NET_PACKET* GetPacket(){assert(HasAny());return &q->packets[i];}
 void Advance(){++i;}
 void Set(){q->packetBegin=i;if(i)q->fragmentBegin=q->packets[i-1].FragmentIndex+q->packets[i-1].FragmentCount;}
};
struct NcmFragmentIterator{
 NcmOsQueue* q;size_t i;
 bool HasAny(){return i<q->fragments.size();}
 NET_FRAGMENT* GetFragment(){assert(HasAny());return &q->fragments[i];}
 NET_FRAGMENT_VIRTUAL_ADDRESS* GetVirtualAddress(){assert(HasAny());return &q->addresses[i];}
 UINT32 GetIndex(){return i;}void Advance(){++i;}
};
static NcmPacketIterator NcmGetAllPackets(NcmOsQueue* q){return {q,q->packetBegin};}
static NcmFragmentIterator NcmGetAllFragments(NcmOsQueue* q){return {q,q->fragmentBegin};}
struct NcmRxQueue{
 NcmOsQueue m_OsQueue;std::vector<std::vector<unsigned char>> frames;size_t nextFrame=0;
 int GetNextFrame(PUCHAR* p,size_t* n){
  if(nextFrame>=frames.size()){*p=nullptr;*n=0;return STATUS_NO_MORE_ENTRIES;}
  auto& f=frames[nextFrame++];*p=f.data();*n=f.size();return STATUS_SUCCESS;
 }
 void Advance();
};
'''
main=r'''
int main(){
 int checks=0;
 for(bool packetAvailable:{false,true})for(bool nullAddress:{false,true}){
  NcmRxQueue rx;std::vector<unsigned char> destination(14,0);
  rx.m_OsQueue.fragments.push_back({14});
  rx.m_OsQueue.addresses.push_back({nullAddress?nullptr:destination.data()});
  if(packetAvailable)rx.m_OsQueue.packets.push_back({});
  rx.frames.push_back(std::vector<unsigned char>(15,0xaa));
  rx.frames.push_back(std::vector<unsigned char>(14,0x55));
  rx.Advance();
  bool delivered=packetAvailable&&!nullAddress;
  assert(rx.m_OsQueue.packetBegin==(delivered?1u:0u));
  assert(rx.m_OsQueue.fragmentBegin==(delivered?1u:0u));
  if(!packetAvailable)assert(rx.nextFrame==0);
  if(delivered){assert(rx.m_OsQueue.fragments[0].ValidLength==14);assert(std::all_of(destination.begin(),destination.end(),[](auto b){return b==0x55;}));}
  else assert(std::all_of(destination.begin(),destination.end(),[](auto b){return b==0;}));
  ++checks;
 }
 NcmRxQueue rx;rx.m_OsQueue.packets.push_back({});rx.frames.push_back(std::vector<unsigned char>(14));rx.Advance();
 assert(rx.nextFrame==0&&rx.m_OsQueue.packetBegin==0);++checks;
 std::printf("RX ring availability/capacity/null destination: %d checks, 0 failures\n",checks);
}
'''
def run_probe():
    with tempfile.TemporaryDirectory(prefix='sideline-ncm-ring-') as tmp:
        cpp=Path(tmp)/'probe.cpp';cpp.write_text(shim+function+main)
        binary=Path(tmp)/'probe'
        subprocess.run(['clang++','-std=c++17','-fsanitize=address,undefined','-g',str(cpp),'-o',str(binary)],check=True)
        return subprocess.run([str(binary)]).returncode

if __name__=='__main__':sys.exit(run_probe())
