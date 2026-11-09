import hashlib
import io
import unittest

from rfw.blowfish import (
    BLOWFISH_IV,
    CHUNK_SIZE,
    Blowfish,
    decrypt_file,
    decrypt_stream,
    get_track_key,
)


class BlowfishTests(unittest.TestCase):
    def test_key_derivation(self):
        # Track 60977514
        key = get_track_key("60977514")
        self.assertEqual(len(key), 16)
        self.assertIsInstance(key, bytes)
        # Consistent for int and str
        self.assertEqual(get_track_key(60977514), key)

    def test_block_roundtrip(self):
        key = b"ASecretKey12345!"
        bf = Blowfish(key)
        xl, xr = 0x12345678, 0x9ABCDEF0
        enc_l, enc_r = bf._encrypt_block(xl, xr)
        dec_l, dec_r = bf._decrypt_block(enc_l, enc_r)
        self.assertEqual((dec_l, dec_r), (xl, xr))

    def test_decrypt_cbc(self):
        key = b"SixteenByteKey!!"
        bf = Blowfish(key)
        # 16 bytes of plaintext
        plain = b"0123456789ABCDEF"
        # Manually encrypt 2 blocks in CBC mode
        prev = BLOWFISH_IV
        cipher_blocks = bytearray()
        import struct

        for i in range(0, len(plain), 8):
            block = plain[i : i + 8]
            b_l, b_r = struct.unpack(">II", block)
            p_l, p_r = struct.unpack(">II", prev)
            c_l, c_r = bf._encrypt_block(b_l ^ p_l, b_r ^ p_r)
            prev = struct.pack(">II", c_l, c_r)
            cipher_blocks.extend(prev)

        decrypted = bf.decrypt_cbc(bytes(cipher_blocks), BLOWFISH_IV)
        self.assertEqual(decrypted, plain)

    def test_decrypt_stream_every_3rd_chunk(self):
        # Simulate a 5-chunk stream (chunk 0, 1, 2, 3, 4)
        # Chunks 0 and 3 are 2048 bytes and encrypted; chunk 1, 2 are 2048 plain; chunk 4 is 500 bytes plain
        key = get_track_key("12345")
        bf = Blowfish(key)

        chunks_orig = [
            b"A" * 2048,
            b"B" * 2048,
            b"C" * 2048,
            b"D" * 2048,
            b"E" * 500,
        ]

        # Encrypt chunk 0 and chunk 3 in CBC
        import struct

        def enc_chunk(data):
            prev = BLOWFISH_IV
            out = bytearray()
            for off in range(0, len(data), 8):
                b_l, b_r = struct.unpack(">II", data[off : off + 8])
                p_l, p_r = struct.unpack(">II", prev)
                c_l, c_r = bf._encrypt_block(b_l ^ p_l, b_r ^ p_r)
                prev = struct.pack(">II", c_l, c_r)
                out.extend(prev)
            return bytes(out)

        chunks_enc = [
            enc_chunk(chunks_orig[0]),
            chunks_orig[1],
            chunks_orig[2],
            enc_chunk(chunks_orig[3]),
            chunks_orig[4],
        ]

        in_stream = io.BytesIO(b"".join(chunks_enc))
        out_stream = io.BytesIO()

        decrypt_stream("12345", in_stream, out_stream)
        self.assertEqual(out_stream.getvalue(), b"".join(chunks_orig))


if __name__ == "__main__":
    unittest.main()
