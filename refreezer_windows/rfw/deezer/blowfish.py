"""Pure Python Blowfish implementation for Deezer stream decryption.

Matches refreezer DeezerDecryptor (Blowfish/CBC/NoPadding, IV 0..7).
Every 3rd chunk of exactly 2048 bytes is decrypted using CBC mode with the track key;
all other chunks are left as-is.
Stdlib only, no third-party libraries or native C modules required.
"""

from __future__ import annotations

import hashlib
import struct
from pathlib import Path
from typing import BinaryIO, Union

from .blowfish_tables import P_INIT, S_INIT

BLOWFISH_IV = b"\x00\x01\x02\x03\x04\x05\x06\x07"
DEEZER_SECRET = b"g4el58wc0zvf9na1"
CHUNK_SIZE = 2048


def get_track_key(track_id: Union[str, int]) -> bytes:
    """Derive 16-byte Blowfish key from Deezer track ID and the fixed secret."""
    md5_id = hashlib.md5(str(track_id).encode("ascii")).hexdigest().lower()
    key = bytearray(16)
    for i in range(16):
        key[i] = ord(md5_id[i]) ^ ord(md5_id[i + 16]) ^ DEEZER_SECRET[i]
    return bytes(key)


class Blowfish:
    """Blowfish cipher with ECB block encryption/decryption and CBC mode."""

    def __init__(self, key: bytes):
        if not (4 <= len(key) <= 56):
            raise ValueError(f"Blowfish key must be 4..56 bytes (got {len(key)})")
        self.p = list(P_INIT)
        self.s = [list(box) for box in S_INIT]

        key_len = len(key)
        j = 0
        for i in range(18):
            data = 0
            for _ in range(4):
                data = (data << 8) | key[j]
                j = (j + 1) % key_len
            self.p[i] ^= data

        xl, xr = 0, 0
        for i in range(0, 18, 2):
            xl, xr = self._encrypt_block(xl, xr)
            self.p[i] = xl
            self.p[i + 1] = xr

        for box in self.s:
            for j in range(0, 256, 2):
                xl, xr = self._encrypt_block(xl, xr)
                box[j] = xl
                box[j + 1] = xr

    def _round(self, x: int) -> int:
        s0, s1, s2, s3 = self.s
        return (((s0[x >> 24] + s1[(x >> 16) & 0xFF]) & 0xFFFFFFFF) ^ s2[(x >> 8) & 0xFF]) + s3[x & 0xFF] & 0xFFFFFFFF

    def _encrypt_block(self, xl: int, xr: int) -> tuple[int, int]:
        p = self.p
        for i in range(16):
            xl ^= p[i]
            xr = (xr ^ self._round(xl)) & 0xFFFFFFFF
            xl, xr = xr, xl
        xl, xr = xr, xl
        xr ^= p[16]
        xl ^= p[17]
        return xl & 0xFFFFFFFF, xr & 0xFFFFFFFF

    def _decrypt_block(self, xl: int, xr: int) -> tuple[int, int]:
        p = self.p
        for i in range(17, 1, -1):
            xl ^= p[i]
            xr = (xr ^ self._round(xl)) & 0xFFFFFFFF
            xl, xr = xr, xl
        xl, xr = xr, xl
        xr ^= p[1]
        xl ^= p[0]
        return xl & 0xFFFFFFFF, xr & 0xFFFFFFFF

    def decrypt_cbc(self, data: bytes, iv: bytes = BLOWFISH_IV) -> bytes:
        """Decrypt data in CBC mode with no padding (data length must be multiple of 8)."""
        if len(data) % 8 != 0:
            raise ValueError(f"Data length must be multiple of 8 (got {len(data)})")
        p = self.p
        s0, s1, s2, s3 = self.s
        out = bytearray(len(data))
        prev_l, prev_r = struct.unpack(">II", iv)

        for offset in range(0, len(data), 8):
            curr_l, curr_r = struct.unpack(">II", data[offset : offset + 8])
            xl, xr = curr_l, curr_r
            for i in range(17, 1, -1):
                xl ^= p[i]
                xr = (xr ^ (((((s0[xl >> 24] + s1[(xl >> 16) & 0xFF]) & 0xFFFFFFFF) ^ s2[(xl >> 8) & 0xFF]) + s3[xl & 0xFF]) & 0xFFFFFFFF)) & 0xFFFFFFFF
                xl, xr = xr, xl
            xl, xr = xr, xl
            xr ^= p[1]
            xl ^= p[0]
            out[offset : offset + 4] = struct.pack(">I", (xl & 0xFFFFFFFF) ^ prev_l)
            out[offset + 4 : offset + 8] = struct.pack(">I", (xr & 0xFFFFFFFF) ^ prev_r)
            prev_l, prev_r = curr_l, curr_r

        return bytes(out)


def decrypt_stream(track_id: Union[str, int], in_stream: BinaryIO, out_stream: BinaryIO) -> int:
    """Decrypt a Deezer audio stream, writing decrypted bytes to out_stream."""
    key = get_track_key(track_id)
    cipher = Blowfish(key)
    chunk_index = 0
    total_bytes = 0

    while True:
        chunk = in_stream.read(CHUNK_SIZE)
        if not chunk:
            break
        if len(chunk) == CHUNK_SIZE and (chunk_index % 3 == 0):
            decrypted = cipher.decrypt_cbc(chunk, BLOWFISH_IV)
            out_stream.write(decrypted)
        else:
            out_stream.write(chunk)
        total_bytes += len(chunk)
        chunk_index += 1

    return total_bytes


def decrypt_file(track_id: Union[str, int], in_path: Union[str, Path], out_path: Union[str, Path]) -> int:
    """Decrypt an encrypted file on disk to out_path."""
    with open(in_path, "rb") as fin, open(out_path, "wb") as fout:
        return decrypt_stream(track_id, fin, fout)
