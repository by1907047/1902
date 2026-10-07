// Sideline experimental validation. Allocation-free; shared by host and tests.
#pragma once
#include <stddef.h>

namespace Apple1902 {
struct Configuration {
    size_t ecmOffset;
    size_t ncmOffset;
    unsigned short mtu;
    unsigned char macIndex;
};

inline bool IsSupported(unsigned vendor, unsigned product)
{ return vendor == 0x05ac && product == 0x1902; }

inline unsigned Read16(const unsigned char* p)
{ return unsigned(p[0]) | (unsigned(p[1]) << 8); }
inline unsigned Read32(const unsigned char* p)
{ return Read16(p) | (Read16(p+2) << 16); }

inline bool ParseConfiguration(const unsigned char* data, size_t size, Configuration& result)
{
    if (!data || size < 9 || data[0] != 9 || data[1] != 2 ||
        data[4] != 4 || data[5] != 1) return false;
    const size_t total = Read16(data+2);
    if (total < 9 || total > size) return false;
    bool settings[4][2] = {};
    bool unions[2] = {}, ecms[2] = {}, ncms[2] = {};
    unsigned current = 4, alt = 0, expectedEndpoints = 0, endpoints = 0, directions = 0;
    Configuration candidate = {};
    for (size_t offset = 9; offset < total;) {
        if (total-offset < 2) return false;
        const unsigned char* p = data+offset;
        const unsigned length = p[0], type = p[1];
        if (length < 2 || length > total-offset) return false;
        if (type == 4) {
            if (current != 4 && (endpoints != expectedEndpoints ||
                (alt == 1 && directions != 3))) return false;
            if (length != 9 || p[2] >= 4 || p[3] > 1) return false;
            current = p[2]; alt = p[3];
            if (settings[current][alt]) return false;
            settings[current][alt] = true;
            const bool control = (current % 2 == 0);
            if (control) {
                if (alt != 0 || p[4] != 0 || p[5] != 2 || p[6] != 0x0d || p[7] != 0)
                    return false;
            } else if (p[4] != (alt == 1 ? 2 : 0) || p[5] != 0x0a ||
                       p[6] != 0 || p[7] != 1) return false;
            expectedEndpoints = p[4]; endpoints = directions = 0;
        } else if (type == 5) {
            if (current == 4 || current % 2 == 0 || alt != 1 || length < 7 ||
                (p[3] & 3) != 2 || Read16(p+4) == 0) return false;
            const unsigned address = p[2];
            if ((address & 0x7f) != (current == 1 ? 1u : 2u)) return false;
            const unsigned direction = (address & 0x80) ? 1 : 2;
            if (directions & direction) return false;
            directions |= direction;
            if (++endpoints > expectedEndpoints) return false;
        } else if (type == 0x24) {
            if (current >= 4 || current % 2 != 0 || alt != 0 || length < 3) return false;
            const unsigned pair = current/2;
            switch (p[2]) {
            case 0:
                if (length < 5) return false;
                break;
            case 6:
                if (length != 5 || unions[pair] || p[3] != current || p[4] != current+1)
                    return false;
                unions[pair] = true;
                break;
            case 0x0f:
                // Adapter subtracts the 14-byte Ethernet header to obtain payload MTU.
                if (length != 13 || ecms[pair] || p[3] == 0 || Read16(p+8) <= 14)
                    return false;
                ecms[pair] = true;
                if (pair == 0) {
                    candidate.ecmOffset = offset;
                    candidate.mtu = (unsigned short)Read16(p+8);
                    candidate.macIndex = p[3];
                }
                break;
            case 0x1a:
                if (length != 6 || ncms[pair]) return false;
                ncms[pair] = true;
                if (pair == 0) candidate.ncmOffset = offset;
                break;
            default:
                break;
            }
        }
        offset += length;
    }
    if (current == 4 || endpoints != expectedEndpoints || (alt == 1 && directions != 3))
        return false;
    for (unsigned i = 0; i < 4; ++i)
        if (!settings[i][0] || (i%2 != 0 && !settings[i][1])) return false;
    for (unsigned i = 0; i < 2; ++i)
        if (!unions[i] || !ecms[i] || !ncms[i]) return false;
    result = candidate;
    return true;
}

template<class Character>
inline bool ParseMac(const Character* text, size_t count, unsigned char* result)
{
    if (!text || !result || count != 12) return false;
    unsigned char bytes[6] = {};
    unsigned nonzero = 0;
    for (unsigned i = 0; i < 12; ++i) {
        const unsigned ch = (unsigned)text[i];
        unsigned value;
        if (ch >= '0' && ch <= '9') value = ch-'0';
        else if (ch >= 'a' && ch <= 'f') value = ch-'a'+10;
        else if (ch >= 'A' && ch <= 'F') value = ch-'A'+10;
        else return false;
        bytes[i/2] = (unsigned char)((bytes[i/2] << 4) | value);
    }
    if (bytes[0] & 1) return false;
    for (unsigned i = 0; i < 6; ++i) nonzero |= bytes[i];
    if (!nonzero) return false;
    for (unsigned i = 0; i < 6; ++i) result[i] = bytes[i];
    return true;
}

inline size_t AlignUp(size_t value, size_t powerOfTwo)
{ return (value + powerOfTwo-1) & ~(powerOfTwo-1); }

// Bytes ntb.cpp CopyNextDatagram needs to place one mtu-sized datagram in an
// empty OUT NTB: NTH, payload divisor/remainder padding, NDP alignment, NDP
// header, the datagram DPE and the terminating null DPE.
inline size_t FirstDatagramNtbSize(bool ntb32, unsigned mtu, unsigned divisor,
                                   unsigned remainder, unsigned alignment)
{
    const size_t nth = ntb32 ? 16 : 12, ndp = ntb32 ? 16 : 8, dpe = ntb32 ? 8 : 4;
    const size_t datagram = AlignUp(nth+14, divisor) + remainder - 14;
    return AlignUp(datagram+mtu, alignment) + ndp + 2*dpe;
}

inline bool ValidateNtb(const unsigned char* data, size_t size, unsigned mtu)
{
    if (!data || size != 28 || Read16(data) != 28 || !(Read16(data+2) & 1) ||
        mtu <= 14 || mtu > 9014) return false;
    // The host selects NTB32 whenever the device advertises it.
    const bool ntb32 = (Read16(data+2) & 2) != 0;
    const unsigned limit = ntb32 ? 0x10000u : 0xffffu;
    // Experimental bounds: reject device-advertised excessive allocations.
    for (unsigned offset = 4; offset <= 16; offset += 12) {
        const unsigned maximum = Read32(data+offset);
        const unsigned divisor = Read16(data+offset+4);
        const unsigned remainder = Read16(data+offset+6);
        const unsigned alignment = Read16(data+offset+8);
        if (divisor == 0 || (divisor & (divisor-1)) || remainder >= divisor ||
            alignment < 4 || (alignment & (alignment-1)) ||
            maximum > limit || maximum < mtu+64+divisor+alignment) return false;
        // Otherwise TX silently drops every maximum-size frame as unfit.
        if (offset == 16 &&
            maximum < FirstDatagramNtbSize(ntb32, mtu, divisor, remainder, alignment))
            return false;
    }
    return true;
}

// Result of one USBD connection-speed capability query.
enum class Capability { Supported, NotSupported, QueryFailed };

// Matches NDIS_LINK_SPEED_UNKNOWN.
constexpr unsigned long long UnknownLinkSpeed = ~0ull;

// Each capability means "operating at this speed or faster". KMDF's
// AT_HIGH_SPEED trait is also set at SuperSpeed, so it cannot tell USB2 from
// USB3. SuperSpeedPlus is not distinguished and reports the Gen 1 rate.
inline unsigned long long LinkSpeedFromCapabilities(Capability superSpeed, Capability highSpeed)
{
    if (superSpeed == Capability::Supported) return 5000000000ull;
    if (superSpeed == Capability::QueryFailed) return UnknownLinkSpeed;
    if (highSpeed == Capability::Supported) return 480000000ull;
    if (highSpeed == Capability::QueryFailed) return UnknownLinkSpeed;
    return 12000000ull;
}
}
