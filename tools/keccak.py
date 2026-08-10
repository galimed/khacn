"""Pure-Python Keccak-256 (the Ethereum variant, NOT NIST SHA3-256).

No dependencies. Implements the Keccak-f[1600] permutation and the
sponge construction with Keccak's original 10*1 padding (0x01 / 0x80),
as used by Ethereum's keccak256 (EVM SHA3 opcode).
"""

MASK64 = (1 << 64) - 1

RHO_OFFSETS = [
    [0, 36, 3, 41, 18],
    [1, 44, 10, 45, 2],
    [62, 6, 43, 15, 61],
    [28, 55, 25, 21, 56],
    [27, 20, 39, 8, 14],
]

ROUND_CONSTANTS = [
    0x0000000000000001, 0x0000000000008082, 0x800000000000808A, 0x8000000080008000,
    0x000000000000808B, 0x0000000080000001, 0x8000000080008081, 0x8000000000008009,
    0x000000000000008A, 0x0000000000000088, 0x0000000080008009, 0x000000008000000A,
    0x000000008000808B, 0x800000000000008B, 0x8000000000008089, 0x8000000000008003,
    0x8000000000008002, 0x8000000000000080, 0x000000000000800A, 0x800000008000000A,
    0x8000000080008081, 0x8000000000008080, 0x0000000080000001, 0x8000000080008008,
]


def _rol(x, n):
    n %= 64
    if n == 0:
        return x & MASK64
    return ((x << n) | (x >> (64 - n))) & MASK64


def _keccak_f(state):
    for rnd in range(24):
        # theta
        c = [state[x] ^ state[x + 5] ^ state[x + 10] ^ state[x + 15] ^ state[x + 20] for x in range(5)]
        d = [c[(x - 1) % 5] ^ _rol(c[(x + 1) % 5], 1) for x in range(5)]
        for x in range(5):
            for y in range(5):
                state[x + 5 * y] ^= d[x]
        # rho + pi
        b = [0] * 25
        for x in range(5):
            for y in range(5):
                b[y + 5 * ((2 * x + 3 * y) % 5)] = _rol(state[x + 5 * y], RHO_OFFSETS[x][y])
        # chi
        for x in range(5):
            for y in range(5):
                state[x + 5 * y] = b[x + 5 * y] ^ ((~b[(x + 1) % 5 + 5 * y]) & b[(x + 2) % 5 + 5 * y] & MASK64)
        # iota
        state[0] ^= ROUND_CONSTANTS[rnd]
    return state


def keccak256(data: bytes) -> bytes:
    rate = 136  # bytes (1088 bits); capacity = 64 bytes (512 bits) -> 256-bit output
    state = [0] * 25

    def absorb_block(block):
        for i in range(rate // 8):
            lane = int.from_bytes(block[i * 8:i * 8 + 8], "little")
            state[i] ^= lane
        _keccak_f(state)

    full_blocks = len(data) // rate
    for i in range(full_blocks):
        absorb_block(data[i * rate:(i + 1) * rate])

    remaining = data[full_blocks * rate:]
    pad_len = rate - len(remaining)
    if pad_len == 1:
        last_block = remaining + b"\x81"
    else:
        last_block = remaining + b"\x01" + b"\x00" * (pad_len - 2) + b"\x80"
    absorb_block(last_block)

    out = bytearray()
    while len(out) < 32:
        for i in range(rate // 8):
            out += state[i].to_bytes(8, "little")
        if len(out) < 32:
            _keccak_f(state)
    return bytes(out[:32])


def eip55_checksum(address_hex: str) -> str:
    """Given a 40-hex-char address (no 0x, any case), return the EIP-55 checksummed form."""
    addr_lower = address_hex.lower()
    digest = keccak256(addr_lower.encode("ascii"))
    digest_hex = digest.hex()
    out = []
    for i, ch in enumerate(addr_lower):
        if ch in "0123456789":
            out.append(ch)
        else:
            nibble = int(digest_hex[i], 16)
            out.append(ch.upper() if nibble >= 8 else ch)
    return "0x" + "".join(out)


if __name__ == "__main__":
    # Known-answer tests before this is trusted for anything.
    empty_hash = keccak256(b"").hex()
    print("empty string hash:", empty_hash, "(len=%d)" % len(empty_hash))

    eip55_vectors = [
        "0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed",
        "0xfB6916095ca1df60bB79Ce92cE3Ea74c37c5d359",
        "0xdbF03B407c01E7cD3CBea99509d93f8DDDC8C6FB",
        "0xD1220A0cf47c7B9Be7A2E6BA89F429762e7b9aDb",
    ]
    for v in eip55_vectors:
        result = eip55_checksum(v[2:])
        assert result == v, (v, result)
    print("EIP-55 KAT vectors: OK (%d/%d)" % (len(eip55_vectors), len(eip55_vectors)))

    khacn = eip55_checksum("11c1b94294A7967092F747434dEE4876EcA5fD53".lower())
    print("KHACN contract checksum ->", khacn)
