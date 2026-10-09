"""Cross-check host OUT-NTB validation against the real ntb.cpp TX template.

For each swept NTB16/NTB32 parameter set, FirstDatagramNtbSize must be the
exact smallest buffer in which CopyNextDatagram accepts an mtu-sized frame, and
ValidateNtb must accept only OUT sizes where that frame fits. Shimmed OS
interfaces only; not a driver or hardware test.
"""
from pathlib import Path
import subprocess
import sys
import tempfile
from ntb_review_probe import root, shim, structures, template

main = r'''
#include "host/apple1902_validation.h"
using Test16=NcmTransferBlock<NcmTransferHeader16,NcmDatagramPointerTable16,NcmDatagramPointer16,
                            UINT16,0x484d434e,0x304d434e,0x314d434e>;
using Test32=NcmTransferBlock<NcmTransferHeader32,NcmDatagramPointerTable32,NcmDatagramPointer32,
                            UINT32,0x686d636e,0x306d636e,0x316d636e>;
static int checks=0,failures=0;
#define CHECK(e) do{++checks;if(!(e)){++failures;std::printf("FAIL %s ntb32=%d mtu=%u div=%u rem=%u align=%u\n",#e,ntb32,mtu,divisor,remainder,alignment);}}while(0)
template<class Ntb>
static bool Fits(size_t capacity,unsigned mtu,unsigned divisor,unsigned remainder,unsigned alignment,bool ntb32){
  Ntb ntb; assert(ntb.InitializeNtb(nullptr,1,alignment,divisor,remainder,ntb32)==0);
  std::vector<uint8_t> buffer(capacity);
  assert(ntb.ReInitializeBuffer(buffer.data(),buffer.size(),NTB_TX)==0);
  NcmPacketIterator packet; packet.packet.resize(mtu,0x5a);
  return ntb.CopyNextDatagram(&packet)==STATUS_SUCCESS;
}
static void Put16(uint8_t* p,unsigned v){p[0]=v&0xff;p[1]=(v>>8)&0xff;}
static void Put32(uint8_t* p,unsigned v){Put16(p,v&0xffff);Put16(p+2,v>>16);}
int main(){
  for(bool ntb32 : {false,true})
  for(unsigned mtu : {15u,64u,1514u,9014u})
  for(unsigned divisor=1;divisor<=1024;divisor*=2)
  for(unsigned remainder : {0u,divisor/2,divisor-1})
  for(unsigned alignment : {4u,8u,64u,512u}){
    const size_t need=Apple1902::FirstDatagramNtbSize(ntb32,mtu,divisor,remainder,alignment);
    const bool fits=ntb32?Fits<Test32>(need,mtu,divisor,remainder,alignment,true)
                         :Fits<Test16>(need,mtu,divisor,remainder,alignment,false);
    const bool shortFits=ntb32?Fits<Test32>(need-1,mtu,divisor,remainder,alignment,true)
                              :Fits<Test16>(need-1,mtu,divisor,remainder,alignment,false);
    CHECK(fits); CHECK(!shortFits);
    // Valid IN parameters; vary only the OUT maximum around both bounds.
    uint8_t params[28]={};
    Put16(params,28); Put16(params+2,ntb32?3:1);
    Put32(params+4,0xffff); Put16(params+8,4); Put16(params+12,4);
    Put16(params+20,divisor); Put16(params+22,remainder); Put16(params+24,alignment);
    const unsigned oldBound=mtu+64+divisor+alignment;
    const unsigned limit=ntb32?0x10000u:0xffffu;
    for(unsigned maximum : {oldBound,unsigned(need-1),unsigned(need),limit}){
      Put32(params+16,maximum);
      const bool accepted=Apple1902::ValidateNtb(params,28,mtu);
      if(accepted){
        const bool real=ntb32?Fits<Test32>(maximum,mtu,divisor,remainder,alignment,true)
                             :Fits<Test16>(maximum,mtu,divisor,remainder,alignment,false);
        CHECK(real);
      }
      CHECK(accepted==(maximum>=oldBound&&maximum>=need&&maximum<=limit));
    }
  }
  std::printf("OUT NTB fit vs real CopyNextDatagram: %d checks, %d failures\n",checks,failures);
  return failures?1:0;
}
'''


def run_probe():
    with tempfile.TemporaryDirectory(prefix='sideline-ncm-fit-') as tmp:
        cpp = Path(tmp)/'fit.cpp'
        cpp.write_text(shim+'\n#pragma pack(push,1)\n'+structures+'\n#pragma pack(pop)\n'+template+main)
        binary = Path(tmp)/'fit'
        subprocess.run(['clang++','-std=c++17','-fsanitize=address,undefined','-g',
                        '-I',str(root),str(cpp),'-o',str(binary)],check=True)
        return subprocess.run([str(binary)]).returncode


if __name__ == '__main__':
    sys.exit(run_probe())
