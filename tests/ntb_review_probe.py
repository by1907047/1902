"""Compile the actual upstream NTB template with minimal OS/allocator shims.

Review-only probes: expected failures reproduce pre-load blockers, not driver tests.
No Windows commands, driver loading or network changes. Files stay in a temp dir.
"""
from pathlib import Path
import subprocess
import tempfile
import sys

root = Path(__file__).resolve().parents[1] / 'NCM-Driver-for-Windows'
source = (root/'common/ntb.cpp').read_text()
template = source[source.index('template <'):source.index('typedef\nNcmTransferBlock<')]
header = (root/'inc/ncm.h').read_text()
structures = header[header.index('struct NcmTransferHeader'):header.index('typedef struct _USB_CDC_NOTIFICATION')]
shim = r'''
#include <cstdint>
#include <cstddef>
#include <cstring>
#include <cstdio>
#include <vector>
#include <memory>
#include <cassert>
#include <algorithm>
#define PAGED
#define _IRQL_requires_max_(x)
#define _Success_(x)
#define _In_
#define _Out_
#define _Outptr_result_buffer_(x)
#define NT_FRE_ASSERT(x) assert(x)
#define NCM_RETURN_IF_NOT_NT_SUCCESS_MSG(expr,msg) do { auto s=(expr); if(s!=0) return s; } while(0)
#define NCM_RETURN_IF_NOT_NT_SUCCESS(expr) NCM_RETURN_IF_NOT_NT_SUCCESS_MSG(expr,"")
#define ALIGN_UP_BY(x,a) (((x)+((a)-1))&~size_t((a)-1))
#define RtlCopyMemory(d,s,n) std::memcpy(d,s,n)
#define RtlZeroMemory(d,n) std::memset(d,0,n)
using std::min;
using UINT8=uint8_t; using UINT16=uint16_t; using UINT32=uint32_t; using UINT64=uint64_t;
using BOOLEAN=bool; using PUCHAR=uint8_t*; using NTSTATUS=int;
constexpr bool FALSE=false;
constexpr int STATUS_SUCCESS=0, STATUS_BUFFER_TOO_SMALL=-1, STATUS_NO_MORE_ENTRIES=-2, STATUS_BAD_DATA=-3;
using NTH_SIG=const UINT32; using NDP_SIG=NTH_SIG;
enum NTB_DIRECTION { NTB_RX,NTB_TX };
struct ETHERNET_HEADER { uint8_t bytes[14]; };
using NETPACKETQUEUE=void*;
struct WDF_OBJECT_ATTRIBUTES { void* ParentObject; };
#define WDF_OBJECT_ATTRIBUTES_INIT(a) ((a)->ParentObject=nullptr)
constexpr int NonPagedPoolNx=0;
struct Memory { std::vector<uint8_t> bytes; };
using WDFMEMORY=Memory*;
static std::vector<std::unique_ptr<Memory>> allocations;
static int WdfMemoryCreate(WDF_OBJECT_ATTRIBUTES*,int,int,size_t count,WDFMEMORY* handle,void*) {
  auto m=std::make_unique<Memory>(); m->bytes.resize(count); *handle=m.get();
  allocations.push_back(std::move(m)); return 0;
}
static void* WdfMemoryGetBuffer(WDFMEMORY m,size_t* size) {
  if(size) *size=m->bytes.size(); return m->bytes.data();
}
struct NcmPacketIterator { std::vector<uint8_t> packet; };
static size_t NcmGetPacketDataLength(NcmPacketIterator* p) { return p->packet.size(); }
static void NcmCopyPacketDataToBuffer(uint8_t* d,NcmPacketIterator* p,size_t n) { std::memcpy(d,p->packet.data(),n); }
'''
main = r'''using Test16=NcmTransferBlock<NcmTransferHeader16,NcmDatagramPointerTable16,NcmDatagramPointer16,
                            UINT16,0x484d434e,0x304d434e,0x314d434e>;
using Test32=NcmTransferBlock<NcmTransferHeader32,NcmDatagramPointerTable32,NcmDatagramPointer32,
                            UINT32,0x686d636e,0x306d636e,0x316d636e>;
template<class Ntb>
static int Positive(size_t exactSize,bool use32) {
  NcmPacketIterator packet; packet.packet.resize(14,0x55);
  Ntb ntb;
  assert(ntb.InitializeNtb(nullptr,1,4,4,0,use32)==0);
  std::vector<uint8_t> shortBuffer(exactSize-1), buffer(exactSize);
  assert(ntb.ReInitializeBuffer(shortBuffer.data(),shortBuffer.size(),NTB_TX)==0);
  assert(ntb.CopyNextDatagram(&packet)==STATUS_BUFFER_TOO_SMALL);
  assert(ntb.ReInitializeBuffer(buffer.data(),buffer.size(),NTB_TX)==0);
  assert(ntb.CopyNextDatagram(&packet)==0);
  size_t transferred=0; ntb.SetNdp(&transferred);
  assert(transferred==exactSize);
  assert(ntb.ReInitializeBuffer(buffer.data(),buffer.size(),NTB_RX)==0);
  PUCHAR datagram=nullptr; size_t size=0;
  assert(ntb.GetNextDatagram(&datagram,&size)==0);
  assert(size==14 && std::memcmp(datagram,packet.packet.data(),14)==0);
  assert(ntb.GetNextDatagram(&datagram,&size)==STATUS_NO_MORE_ENTRIES);
  std::printf("NTB%s exact-fit=%zu and one-byte-short checks passed\n",use32?"32":"16",exactSize);
  return 0;
}
int main(int argc,char** argv) {
  if(argc!=2) return 2;
  if(std::strcmp(argv[1],"valid32")==0) return Positive<Test32>(64,true);
  if(std::strcmp(argv[1],"valid16")==0) return Positive<Test16>(44,false);
  Test32 ntb;
  assert(ntb.InitializeNtb(nullptr,1,4,4,0,true)==0);
  if(std::strcmp(argv[1],"null")==0) {
    const auto result=ntb.ReInitializeBuffer(nullptr,0,NTB_RX);
    std::printf("null RX buffer: actual %d, expected %d\n",result,STATUS_BAD_DATA);
    return result==STATUS_BAD_DATA ? 0 : 1;
  }
  if(std::strcmp(argv[1],"chain")==0) {
    // Literal layout: data at16/32, NDPs at48/80. Both chain orders are valid.
    for(bool reverse : {false,true}) {
      std::vector<uint8_t> buffer(112);
      std::memset(buffer.data()+16,0xaa,14); std::memset(buffer.data()+32,0xbb,14);
      auto* nth=reinterpret_cast<NcmTransferHeader32*>(buffer.data());
      nth->Signature=0x686d636e; nth->HeaderLength=16; nth->BlockLength=112; nth->NdpIndex=reverse?80:48;
      for(size_t offset : {size_t(48),size_t(80)}) {
        auto* ndp=reinterpret_cast<NcmDatagramPointerTable32*>(buffer.data()+offset);
        ndp->Signature=0x306d636e; ndp->Length=32;
        ndp->NextNdpIndex=offset==(reverse?80:48) ? (reverse?48:80) : 0;
        auto* entry=reinterpret_cast<NcmDatagramPointer32*>(buffer.data()+offset+16);
        entry->DatagramIndex=offset==48?16:32; entry->DatagramLength=14;
      }
      assert(ntb.ReInitializeBuffer(buffer.data(),buffer.size(),NTB_RX)==0);
      PUCHAR data=nullptr; size_t size=0;
      assert(ntb.GetNextDatagram(&data,&size)==0 && size==14 && *data==(reverse?0xbb:0xaa));
      assert(ntb.GetNextDatagram(&data,&size)==0 && size==14 && *data==(reverse?0xaa:0xbb));
      assert(ntb.GetNextDatagram(&data,&size)==STATUS_NO_MORE_ENTRIES && data==nullptr && size==0);
    }
    std::puts("forward/backward two-NDP chains preserve frames and clear end outputs");
    return 0;
  }
  if(std::strcmp(argv[1],"prefixes")==0) {
    std::vector<uint8_t> buffer(16,0);
    Test16 short16;
    assert(short16.InitializeNtb(nullptr,1,4,4,0,false)==0);
    for(size_t length=0;length<12;++length)
      assert(short16.ReInitializeBuffer(length?buffer.data():nullptr,length,NTB_RX)==STATUS_BAD_DATA);
    for(size_t length=0;length<16;++length)
      assert(ntb.ReInitializeBuffer(length?buffer.data():nullptr,length,NTB_RX)==STATUS_BAD_DATA);
    std::puts("all NTB16/32 truncated NTH prefixes rejected");
    return 0;
  }
  if(std::strcmp(argv[1],"empty")==0 || std::strcmp(argv[1],"cycle")==0 ||
     std::strcmp(argv[1],"skip")==0 || std::strcmp(argv[1],"emptycycle")==0) {
    const bool emptycycle=std::strcmp(argv[1],"emptycycle")==0;
    const bool skip=std::strcmp(argv[1],"skip")==0;
    const bool cycle=std::strcmp(argv[1],"cycle")==0 || emptycycle;
    std::vector<uint8_t> buffer(cycle ? 64 : 96);
    auto* nth=reinterpret_cast<NcmTransferHeader32*>(buffer.data());
    nth->Signature=0x686d636e; nth->HeaderLength=16; nth->BlockLength=static_cast<uint32_t>(buffer.size()); nth->NdpIndex=32;
    auto* ndp=reinterpret_cast<NcmDatagramPointerTable32*>(buffer.data()+32);
    ndp->Signature=0x306d636e; ndp->Length=32; ndp->NextNdpIndex=cycle ? 32 : 64;
    if(!cycle){
      auto* second=reinterpret_cast<NcmDatagramPointerTable32*>(buffer.data()+64);
      second->Signature=0x306d636e; second->Length=32;
      if(skip){
        auto* data=reinterpret_cast<NcmDatagramPointer32*>(buffer.data()+80);
        data->DatagramIndex=16; data->DatagramLength=14;
      }
    }
    auto* entry=reinterpret_cast<NcmDatagramPointer32*>(buffer.data()+48);
    if(cycle && !emptycycle){entry->DatagramIndex=16; entry->DatagramLength=14;}
    const auto init=ntb.ReInitializeBuffer(buffer.data(),buffer.size(),NTB_RX);
    if(cycle) {
      if(init!=STATUS_BAD_DATA){std::printf("FAIL: cyclic header preflight actual=%d expected=%d\n",init,STATUS_BAD_DATA);return 1;}
      // A rejected NTB exposes zero DPEs; subsequent object reuse stays valid.
      ndp->NextNdpIndex=0;entry->DatagramIndex=16;entry->DatagramLength=14;
      assert(ntb.ReInitializeBuffer(buffer.data(),buffer.size(),NTB_RX)==STATUS_SUCCESS);
      PUCHAR data=nullptr;size_t length=0;
      assert(ntb.GetNextDatagram(&data,&length)==STATUS_SUCCESS && data==buffer.data()+16 && length==14);
      assert(ntb.GetNextDatagram(&data,&length)==STATUS_NO_MORE_ENTRIES && data==nullptr && length==0);
      std::puts("cyclic header rejected before DPE, valid reuse PASS");return 0;
    }
    assert(init==STATUS_SUCCESS);
    PUCHAR datagram=reinterpret_cast<PUCHAR>(uintptr_t(1)); size_t size=999;
    if(skip){
      assert(ntb.GetNextDatagram(&datagram,&size)==0 && datagram==buffer.data()+16 && size==14);
      assert(ntb.GetNextDatagram(&datagram,&size)==STATUS_NO_MORE_ENTRIES && datagram==nullptr && size==0);
      std::puts("empty-to-nonempty chain skips terminators and returns real frame");
      return 0;
    }
    int result=0;
    for(int i=0;i<(cycle?16:1) && result==0;++i) result=ntb.GetNextDatagram(&datagram,&size);
    const int expected=cycle ? STATUS_BAD_DATA : STATUS_NO_MORE_ENTRIES;
    std::printf("%s NDP: actual %d, expected %d, cleared-output=%d\n",cycle?"cyclic":"empty",result,expected,datagram==nullptr && size==0);
    if(result!=expected || datagram!=nullptr || size!=0) return 1;
    if(cycle){
      ndp->NextNdpIndex=0; entry->DatagramIndex=16; entry->DatagramLength=14;
      assert(ntb.ReInitializeBuffer(buffer.data(),buffer.size(),NTB_RX)==0);
      assert(ntb.GetNextDatagram(&datagram,&size)==0 && datagram==buffer.data()+16 && size==14);
      assert(ntb.GetNextDatagram(&datagram,&size)==STATUS_NO_MORE_ENTRIES && datagram==nullptr && size==0);
      std::puts("valid reuse after traversal-budget exhaustion passed");
    }
    return 0;
  }
  if(std::strcmp(argv[1],"tx")==0) {
    std::vector<uint8_t> buffer(56);
    assert(ntb.ReInitializeBuffer(buffer.data(),buffer.size(),NTB_TX)==0);
    NcmPacketIterator packet; packet.packet.resize(14,0x55);
    const auto result=ntb.CopyNextDatagram(&packet);
    // NTH16-byte + 2-byte pad + Ethernet14 + NDP16 + data/null DPEs16 =64.
    std::printf("56-byte capacity, 64-byte final NTB needed: actual status %d, expected %d\n",result,STATUS_BUFFER_TOO_SMALL);
    return result==STATUS_BUFFER_TOO_SMALL ? 0 : 1;
  }
  std::vector<uint8_t> buffer(52);
  auto* nth=reinterpret_cast<NcmTransferHeader32*>(buffer.data());
  nth->Signature=0x686d636e; nth->HeaderLength=16; nth->BlockLength=52; nth->NdpIndex=16;
  auto* ndp=reinterpret_cast<NcmDatagramPointerTable32*>(buffer.data()+16);
  ndp->Signature=0x306d636e; ndp->Length=36;
  for(size_t offset : {size_t(32),size_t(40)}) {
    auto* entry=reinterpret_cast<NcmDatagramPointer32*>(buffer.data()+offset);
    entry->DatagramIndex=16; entry->DatagramLength=14;
  }
  uint32_t index=16; std::memcpy(buffer.data()+48,&index,4);
  // Incomplete 8-byte last DPE: reject before reading DatagramLength beyond byte52.
  const auto result=ntb.ReInitializeBuffer(buffer.data(),buffer.size(),NTB_RX);
  std::printf("malformed NTB32 NDP length36: actual %d, expected %d\n",result,STATUS_BAD_DATA);
  return result==STATUS_BAD_DATA ? 0 : 1;
}
'''
def run_probe():
    with tempfile.TemporaryDirectory(prefix='sideline-ncm-review-') as tmp:
        cpp = Path(tmp)/'review.cpp'
        cpp.write_text(shim+'\n#pragma pack(push,1)\n'+structures+'\n#pragma pack(pop)\n'+template+main)
        binary = Path(tmp)/'review'
        subprocess.run(['clang++','-std=c++17','-fsanitize=address,undefined','-g',str(cpp),'-o',str(binary)],check=True)
        outcome = subprocess.run([str(binary), sys.argv[1]])
        return outcome.returncode


if __name__ == '__main__':
    sys.exit(run_probe())
