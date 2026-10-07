#include <cstdio>
#include <vector>
#include <cstddef>

#if __has_include("../NCM-Driver-for-Windows/host/apple1902_validation.h")
#include "../NCM-Driver-for-Windows/host/apple1902_validation.h"
using namespace Apple1902;
static int failures = 0, checks = 0;
#define CHECK(expr) do { ++checks; if (!(expr)) { std::printf("FAIL line %d: %s\n",__LINE__,#expr); ++failures; } } while (0)

// Synthetic fixture: observed 4-interface SS shape, hand-chosen functional values.
// Not a raw capture: USBTreeView did not print the ECM descriptor's payload fields.
static std::vector<unsigned char> Fixture()
{
    return {
        9,2,173,0,4,1,0,0xc0,0,
        9,4,0,0,0,2,0x0d,0,6,
        5,0x24,0,0x10,1, 5,0x24,6,0,1,
        13,0x24,0x0f,4,0,0,0,0,0xea,5,0,0,0,
        6,0x24,0x1a,0,1,0,
        9,4,1,0,0,0x0a,0,1,9,
        9,4,1,1,2,0x0a,0,1,9,
        7,5,0x81,2,0,4,0, 6,0x30,15,0,0,0,
        7,5,1,2,0,4,0, 6,0x30,15,0,0,0,
        9,4,2,0,0,2,0x0d,0,8,
        5,0x24,0,0x10,1, 5,0x24,6,2,3,
        13,0x24,0x0f,5,0,0,0,0,0xea,5,0,0,0,
        6,0x24,0x1a,0,1,0,
        9,4,3,0,0,0x0a,0,1,10,
        9,4,3,1,2,0x0a,0,1,10,
        7,5,0x82,2,0,4,0, 6,0x30,15,0,0,0,
        7,5,2,2,0,4,0, 6,0x30,15,0,0,0
    };
}

int main()
{
    // Detect reverting to 1905 detection or admitting another USB vendor.
    CHECK(IsSupported(0x05ac,0x1902));
    CHECK(!IsSupported(0x05ac,0x1905));
    CHECK(!IsSupported(0x1234,0x1902));
    Configuration c{};
    auto good = Fixture();
    CHECK(good.size()==173);
    CHECK(ParseConfiguration(good.data(),good.size(),c));
    CHECK(c.ecmOffset==28 && c.ncmOffset==41 && c.mtu==1514 && c.macIndex==4);
    // Detect missing bounds/progress checks, never run the old infinite loop.
    for (size_t size=0;size<good.size();++size)
        CHECK(!ParseConfiguration(good.data(),size,c));
    for (size_t p=9;p<good.size();p+=good[p]) {
        auto bad=good; bad[p]=0;
        CHECK(!ParseConfiguration(bad.data(),bad.size(),c));
        bad=good; bad[p]=1;
        CHECK(!ParseConfiguration(bad.data(),bad.size(),c));
        bad=good; bad[p]=255;
        CHECK(!ParseConfiguration(bad.data(),bad.size(),c));
    }
    // Shrink both returned buffer and wTotalLength, so truncation reaches the walker.
    for (size_t size=9;size<good.size();++size) {
        auto truncated=good; truncated.resize(size);
        truncated[2]=(unsigned char)size; truncated[3]=0;
        // At 167 the last optional SS companion is entirely absent, not half-read.
        const bool expectedValid = (size == 167);
        CHECK(ParseConfiguration(truncated.data(),truncated.size(),c) == expectedValid);
    }
    auto bad=good; bad[2]=174; CHECK(!ParseConfiguration(bad.data(),bad.size(),c));
    bad=good; bad[15]=0; CHECK(!ParseConfiguration(bad.data(),bad.size(),c)); // wrong control subclass
    bad=good; bad[26]=2; CHECK(!ParseConfiguration(bad.data(),bad.size(),c)); // wrong union master
    bad=good; bad[49]=0; CHECK(!ParseConfiguration(bad.data(),bad.size(),c)); // duplicate IF0 / missing IF1
    bad=good; bad[30]=0x1a; CHECK(!ParseConfiguration(bad.data(),bad.size(),c)); // missing ECM / duplicate NCM
    bad=good; bad[67]=0x01; CHECK(!ParseConfiguration(bad.data(),bad.size(),c)); // missing IN bulk
    bad=good; bad[69]=0; bad[70]=0; CHECK(!ParseConfiguration(bad.data(),bad.size(),c)); // zero packet size
    bad=good; bad[36]=14; bad[37]=0;
    CHECK(!ParseConfiguration(bad.data(),bad.size(),c)); // adapter would have zero payload MTU
    unsigned char mac[6]{};
    CHECK(ParseMac(L"02aB3456789c",12,mac));
    CHECK(mac[0]==2 && mac[1]==0xab && mac[5]==0x9c);
    CHECK(!ParseMac(L"02aB3456789",11,mac));
    CHECK(!ParseMac(L"02aB3456789g",12,mac));
    CHECK(!ParseMac(L"01aB3456789c",12,mac)); // multicast
    CHECK(!ParseMac(L"000000000000",12,mac));
    // NTB response per CDC NCM layout; expected size/divisors derived independently.
    std::vector<unsigned char> ntb={28,0,3,0,0,0,1,0,4,0,0,0,4,0,0,0,
                                  0,0,1,0,4,0,0,0,4,0,16,0};
    CHECK(ValidateNtb(ntb.data(),ntb.size(),1514));
    CHECK(!ValidateNtb(ntb.data(),ntb.size(),14));
    CHECK(!ValidateNtb(ntb.data(),27,1514));
    auto nbad=ntb; nbad[20]=0; CHECK(!ValidateNtb(nbad.data(),28,1514)); // divide by zero
    nbad=ntb; nbad[22]=4; CHECK(!ValidateNtb(nbad.data(),28,1514)); // remainder >= divisor
    nbad=ntb; nbad[24]=3; CHECK(!ValidateNtb(nbad.data(),28,1514)); // unsafe non-power-of-two alignment
    nbad=ntb; nbad[16]=1; nbad[18]=0; CHECK(!ValidateNtb(nbad.data(),28,1514)); // undersized output
    nbad=ntb; nbad[2]=2; CHECK(!ValidateNtb(nbad.data(),28,1514)); // no mandatory NTB16
    nbad=ntb; nbad[2]=1;
    CHECK(!ValidateNtb(nbad.data(),28,1514)); // NTB16 cannot emit transfer length65536
    nbad[4]=255; nbad[5]=255; nbad[6]=0;
    nbad[16]=255; nbad[17]=255; nbad[18]=0;
    CHECK(ValidateNtb(nbad.data(),28,1514)); // representable NTB16 upper bound
    // Single-byte mutations exercise parser bounds under ASan/UBSan; not all mutations are invalid.
    for (size_t offset=0;offset<good.size();++offset)
        for (unsigned byte=0;byte<256;++byte) {
            auto mutated=good; mutated[offset]=(unsigned char)byte;
            (void)ParseConfiguration(mutated.data(),mutated.size(),c);
        }
    std::printf("%d checks, %d failures\n",checks,failures);
    return failures?1:0;
}
#else
int main() { std::puts("FAIL: production 1902 validation not implemented"); return 1; }
#endif
