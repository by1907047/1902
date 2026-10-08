"""Production NTB maximum-chain/fail-closed regression; local shims, not kernel qualification."""
from pathlib import Path
import subprocess
import tempfile
import ntb_review_probe as fixture

MAIN = r'''
using Test16=NcmTransferBlock<NcmTransferHeader16,NcmDatagramPointerTable16,NcmDatagramPointer16,
                            UINT16,0x484d434e,0x304d434e,0x314d434e>;
using Test32=NcmTransferBlock<NcmTransferHeader32,NcmDatagramPointerTable32,NcmDatagramPointer32,
                            UINT32,0x686d636e,0x306d636e,0x316d636e>;
static size_t checks=0;
template<class Ntb,class Nth,class Ndp,class Dpe>
static void Matrix(bool use32,size_t block) {
 for(size_t skew=0;skew<8;++skew) for(int orderKind=0;orderKind<3;++orderKind) for(bool empty:{false,true}) {
  const size_t stride=sizeof(Ndp)+2*sizeof(Dpe), first=sizeof(Nth);
  const size_t count=(block-first-(empty?0:14))/stride;
  const size_t payload=first+count*stride;
  std::vector<uint8_t> storage(block+skew,0);auto* bytes=storage.data()+skew;
  auto* nth=reinterpret_cast<Nth*>(bytes);nth->Signature=use32?0x686d636e:0x484d434e;
  nth->HeaderLength=sizeof(Nth);nth->BlockLength=block;
  std::vector<size_t> order;
  if(orderKind==0) for(size_t n=0;n<count;++n) order.push_back(n);
  if(orderKind==1) for(size_t n=count;n>0;--n) order.push_back(n-1);
  if(orderKind==2) {for(size_t n=0;n<count;n+=2) order.push_back(n);for(size_t n=(count%2?count-2:count-1);n<count;n-=2) order.push_back(n);}
  assert(order.size()==count);nth->NdpIndex=first+order[0]*stride;
  for(size_t n=0;n<count;++n) {
   auto* header=reinterpret_cast<Ndp*>(bytes+first+order[n]*stride);
   header->Signature=use32?0x306d636e:0x304d434e;header->Length=stride;
   header->NextNdpIndex=n+1<count?first+order[n+1]*stride:0;
   auto* dpe=reinterpret_cast<Dpe*>(reinterpret_cast<uint8_t*>(header)+sizeof(Ndp));
   if(!empty){dpe->DatagramIndex=payload;dpe->DatagramLength=14;}
  }
  Ntb ntb;assert(ntb.InitializeNtb(nullptr,1,4,4,0,use32)==STATUS_SUCCESS);
  auto drain=[&](){size_t delivered=0,size=0;PUCHAR data=nullptr;NTSTATUS status;
   while((status=ntb.GetNextDatagram(&data,&size))==STATUS_SUCCESS){assert(size==14&&data==bytes+payload);++delivered;assert(delivered<=count);}
   assert(status==STATUS_NO_MORE_ENTRIES&&!data&&size==0);return delivered;};
  auditHeaderReads=0;assert(ntb.ReInitializeBuffer(bytes,block,NTB_RX)==STATUS_SUCCESS);
  assert(drain()==(empty?0:count));
  assert(auditHeaderReads<=3*((count+1)/2)+count);
  if(skew==0)std::printf("format=%u block=%zu tables=%zu order=%d empty=%d header_reads=%zu bound=%zu\n",use32?32:16,block,count,orderKind,int(empty),auditHeaderReads,3*((count+1)/2)+count);
  auto* last=reinterpret_cast<Ndp*>(bytes+first+order.back()*stride);
  const auto signature=last->Signature;
  for(int bad=0;bad<5;++bad){
   last->NextNdpIndex=0;last->Signature=signature;last->Length=stride;
   if(bad==0)last->NextNdpIndex=nth->NdpIndex;
   if(bad==1)last->NextNdpIndex=first+order[count/2]*stride;
   if(bad==2)last->Signature=0xdeadbeef;
   if(bad==3)last->Length=stride-1;
   if(bad==4)last->NextNdpIndex=decltype(last->NextNdpIndex)(~decltype(last->NextNdpIndex)(0));
   auditHeaderReads=0;assert(ntb.ReInitializeBuffer(bytes,block,NTB_RX)==STATUS_BAD_DATA);
   assert(auditHeaderReads<=3*(block/stride));
   PUCHAR data=reinterpret_cast<PUCHAR>(uintptr_t(1));size_t length=999;
   assert(ntb.GetNextDatagram(&data,&length)==STATUS_NO_MORE_ENTRIES&&!data&&length==0);
   ++checks;
  }
  last->NextNdpIndex=0;last->Signature=signature;last->Length=stride;
  assert(ntb.ReInitializeBuffer(bytes,block,NTB_RX)==STATUS_SUCCESS);assert(drain()==(empty?0:count));
  // Every NTH prefix and one-byte truncated maximum transfer fails closed.
  for(size_t length=0;length<sizeof(Nth);++length){
   assert(ntb.ReInitializeBuffer(length?bytes:nullptr,length,NTB_RX)==STATUS_BAD_DATA);
   PUCHAR data=reinterpret_cast<PUCHAR>(uintptr_t(1));size_t size=999;
   assert(ntb.GetNextDatagram(&data,&size)==STATUS_NO_MORE_ENTRIES&&!data&&size==0);++checks;
  }
  assert(ntb.ReInitializeBuffer(bytes,block-1,NTB_RX)==STATUS_BAD_DATA);
  PUCHAR data=nullptr;size_t length=0;assert(ntb.GetNextDatagram(&data,&length)==STATUS_NO_MORE_ENTRIES&&!data&&!length);
  nth->NdpIndex=0;assert(ntb.ReInitializeBuffer(bytes,block,NTB_RX)==STATUS_NO_MORE_ENTRIES);
  assert(ntb.GetNextDatagram(&data,&length)==STATUS_NO_MORE_ENTRIES&&!data&&!length);
  ++checks;
 }
}
int main(){
 static_assert(alignof(NcmTransferHeader16)==1&&alignof(NcmTransferHeader32)==1,"packed production structures");
 Matrix<Test16,NcmTransferHeader16,NcmDatagramPointerTable16,NcmDatagramPointer16>(false,65535);
 Matrix<Test32,NcmTransferHeader32,NcmDatagramPointerTable32,NcmDatagramPointer32>(true,65536);
 std::printf("NTB chain preflight: %zu checks PASS; no Windows device exercised\n",checks);
}
'''

def main():
    # Instrument local copies only; no hook or counter is added to the driver.
    template=fixture.template.replace("        const NDP & ndpHeader =", "        ++auditHeaderReads;\n        const NDP & ndpHeader =",1)
    template=template.replace("                const NDP & header =", "                ++auditHeaderReads;\n                const NDP & header =",1)
    with tempfile.TemporaryDirectory(prefix="apple1902-chain-regression-") as temporary:
        cpp=Path(temporary)/"chain.cpp";binary=Path(temporary)/"chain"
        cpp.write_text(fixture.shim+"\nstatic size_t auditHeaderReads=0;\n#pragma pack(push,1)\n"+fixture.structures+"\n#pragma pack(pop)\n"+template+MAIN)
        subprocess.run(["clang++","-std=c++17","-O1","-fsanitize=address,undefined","-fno-sanitize-recover=all","-g",str(cpp),"-o",str(binary)],check=True,timeout=60)
        subprocess.run([str(binary)],check=True,timeout=20)

if __name__=="__main__":main()
