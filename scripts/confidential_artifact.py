"""Encrypt same-run GitHub workflow transfers without publishing plaintext artifacts."""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import os
import stat
import struct
import sys
import tempfile
from collections.abc import Iterator
from contextlib import suppress
from pathlib import Path
from typing import BinaryIO, Final

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

MAGIC: Final = b"MGXFER1\n"
SCHEMA: Final = "modelguard.confidential-artifact.v1"
CHUNK_BYTES: Final = 1024 * 1024
MAX_TRANSFER_BYTES: Final = 4 * 1024 * 1024 * 1024
MAX_HEADER_BYTES: Final = 16 * 1024
NONCE_BYTES: Final = 12
KEY_BYTES: Final = 32


class TransferRefusal(RuntimeError):
    """A confidential transfer failed a closed validation boundary."""


def _chunks(handle: BinaryIO, remaining: int | None = None) -> Iterator[bytes]:
    total = 0
    while remaining is None or total < remaining:
        requested = CHUNK_BYTES if remaining is None else min(CHUNK_BYTES, remaining - total)
        chunk = handle.read(requested)
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_TRANSFER_BYTES:
            raise TransferRefusal("transfer exceeds the approved size ceiling")
        yield chunk
    if remaining is not None and total != remaining:
        raise TransferRefusal("encrypted transfer is truncated")


def _regular_input(path: Path) -> None:
    try:
        attributes = path.lstat()
    except OSError as error:
        raise TransferRefusal("transfer input is unavailable") from error
    if not stat.S_ISREG(attributes.st_mode) or path.is_symlink():
        raise TransferRefusal("transfer input must be an exact regular file")
    if attributes.st_size > MAX_TRANSFER_BYTES:
        raise TransferRefusal("transfer exceeds the approved size ceiling")


def _decode_key(value: str) -> bytes:
    if not value or len(value) > MAX_HEADER_BYTES:
        raise TransferRefusal("key material has an invalid encoded length")
    try:
        return base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as error:
        raise TransferRefusal("key material is not strict Base64") from error


def _load_public_key(value: str) -> rsa.RSAPublicKey:
    try:
        key = serialization.load_der_public_key(_decode_key(value))
    except (TypeError, ValueError) as error:
        raise TransferRefusal("public key cannot be parsed") from error
    if not isinstance(key, rsa.RSAPublicKey) or key.key_size < 3072:
        raise TransferRefusal("an RSA public key of at least 3072 bits is required")
    return key


def _load_private_key_from_stdin() -> rsa.RSAPrivateKey:
    encoded = sys.stdin.buffer.read(MAX_HEADER_BYTES + 1)
    if len(encoded) > MAX_HEADER_BYTES:
        raise TransferRefusal("private key input exceeds its bound")
    try:
        value = encoded.decode("ascii").strip()
        key = serialization.load_der_private_key(_decode_key(value), password=None)
    except (UnicodeDecodeError, TypeError, ValueError) as error:
        raise TransferRefusal("private key cannot be parsed") from error
    if not isinstance(key, rsa.RSAPrivateKey) or key.key_size < 3072:
        raise TransferRefusal("an RSA private key of at least 3072 bits is required")
    return key


def _hash_file(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in _chunks(handle):
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()


def _aad(size: int, digest: str) -> bytes:
    return json.dumps(
        {"plaintext_sha256": digest, "plaintext_size": size, "schema_version": SCHEMA},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")


def _strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise TransferRefusal("encrypted transfer header contains a duplicate field")
        value[key] = item
    return value


def _atomic_target(output: Path) -> tuple[int, Path]:
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists() or output.is_symlink():
        raise TransferRefusal("refusing to overwrite an existing transfer output")
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{output.name}.", dir=output.parent)
    os.fchmod(descriptor, 0o600)
    return descriptor, Path(temporary_name)


def _publish(descriptor: int, temporary: Path, output: Path) -> None:
    os.fsync(descriptor)
    os.close(descriptor)
    os.replace(temporary, output)
    os.chmod(output, 0o600)
    directory = os.open(output.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def encrypt(input_path: Path, output_path: Path, public_key_b64: str) -> None:
    """Encrypt one regular transfer using streaming AES-GCM and an RSA-wrapped key."""

    _regular_input(input_path)
    plaintext_size, plaintext_sha256 = _hash_file(input_path)
    public_key = _load_public_key(public_key_b64)
    content_key = os.urandom(KEY_BYTES)
    nonce = os.urandom(NONCE_BYTES)
    wrapped_key = public_key.encrypt(
        content_key,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )
    encryptor = Cipher(algorithms.AES(content_key), modes.GCM(nonce)).encryptor()
    encryptor.authenticate_additional_data(_aad(plaintext_size, plaintext_sha256))
    descriptor, temporary = _atomic_target(output_path)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as output, input_path.open("rb") as source:
            output.write(MAGIC)
            for chunk in _chunks(source):
                output.write(encryptor.update(chunk))
            output.write(encryptor.finalize())
            header = json.dumps(
                {
                    "cipher": "AES-256-GCM",
                    "nonce": base64.b64encode(nonce).decode("ascii"),
                    "plaintext_sha256": plaintext_sha256,
                    "plaintext_size": plaintext_size,
                    "schema_version": SCHEMA,
                    "tag": base64.b64encode(encryptor.tag).decode("ascii"),
                    "wrapped_key": base64.b64encode(wrapped_key).decode("ascii"),
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("ascii")
            if len(header) > MAX_HEADER_BYTES:
                raise TransferRefusal("encrypted transfer header exceeds its bound")
            output.write(header)
            output.write(struct.pack(">Q", len(header)))
            output.flush()
        _publish(descriptor, temporary, output_path)
    except Exception:
        with suppress(OSError):
            os.close(descriptor)
        temporary.unlink(missing_ok=True)
        raise


def _read_header(source: BinaryIO, total_size: int) -> tuple[dict[str, object], int]:
    if total_size < len(MAGIC) + 8:
        raise TransferRefusal("encrypted transfer is truncated")
    source.seek(total_size - 8)
    length_bytes = source.read(8)
    if len(length_bytes) != 8:
        raise TransferRefusal("encrypted transfer has no complete header length")
    header_size = struct.unpack(">Q", length_bytes)[0]
    if header_size == 0 or header_size > MAX_HEADER_BYTES:
        raise TransferRefusal("encrypted transfer header size is invalid")
    ciphertext_size = total_size - len(MAGIC) - header_size - 8
    if ciphertext_size < 0 or ciphertext_size > MAX_TRANSFER_BYTES:
        raise TransferRefusal("encrypted transfer payload size is invalid")
    source.seek(len(MAGIC) + ciphertext_size)
    header_bytes = source.read(header_size)
    try:
        parsed = json.loads(header_bytes, object_pairs_hook=_strict_object)
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as error:
        raise TransferRefusal("encrypted transfer header is malformed") from error
    if not isinstance(parsed, dict):
        raise TransferRefusal("encrypted transfer header must be an object")
    expected_fields = {
        "cipher",
        "nonce",
        "plaintext_sha256",
        "plaintext_size",
        "schema_version",
        "tag",
        "wrapped_key",
    }
    if set(parsed) != expected_fields:
        raise TransferRefusal("encrypted transfer header fields are invalid")
    return parsed, ciphertext_size


def decrypt(input_path: Path, output_path: Path) -> None:
    """Decrypt an authenticated transfer with private key material supplied only on stdin."""

    _regular_input(input_path)
    private_key = _load_private_key_from_stdin()
    total_size = input_path.stat().st_size
    with input_path.open("rb") as source:
        if source.read(len(MAGIC)) != MAGIC:
            raise TransferRefusal("encrypted transfer magic is invalid")
        header, ciphertext_size = _read_header(source, total_size)
        if header["schema_version"] != SCHEMA or header["cipher"] != "AES-256-GCM":
            raise TransferRefusal("encrypted transfer contract identity is invalid")
        plaintext_size = header["plaintext_size"]
        plaintext_sha256 = header["plaintext_sha256"]
        if (
            not isinstance(plaintext_size, int)
            or isinstance(plaintext_size, bool)
            or plaintext_size < 0
            or plaintext_size > MAX_TRANSFER_BYTES
            or plaintext_size != ciphertext_size
            or not isinstance(plaintext_sha256, str)
            or len(plaintext_sha256) != 64
            or any(character not in "0123456789abcdef" for character in plaintext_sha256)
        ):
            raise TransferRefusal("encrypted transfer plaintext identity is invalid")
        try:
            nonce = base64.b64decode(str(header["nonce"]), validate=True)
            tag = base64.b64decode(str(header["tag"]), validate=True)
            wrapped_key = base64.b64decode(str(header["wrapped_key"]), validate=True)
            content_key = private_key.decrypt(
                wrapped_key,
                padding.OAEP(
                    mgf=padding.MGF1(algorithm=hashes.SHA256()),
                    algorithm=hashes.SHA256(),
                    label=None,
                ),
            )
        except (binascii.Error, ValueError) as error:
            raise TransferRefusal("encrypted transfer key material is invalid") from error
        if len(nonce) != NONCE_BYTES or len(tag) != 16 or len(content_key) != KEY_BYTES:
            raise TransferRefusal("encrypted transfer cryptographic sizes are invalid")
        decryptor = Cipher(algorithms.AES(content_key), modes.GCM(nonce, tag)).decryptor()
        decryptor.authenticate_additional_data(_aad(plaintext_size, plaintext_sha256))
        descriptor, temporary = _atomic_target(output_path)
        digest = hashlib.sha256()
        size = 0
        try:
            source.seek(len(MAGIC))
            with os.fdopen(descriptor, "wb", closefd=False) as output:
                for chunk in _chunks(source, ciphertext_size):
                    plaintext = decryptor.update(chunk)
                    size += len(plaintext)
                    digest.update(plaintext)
                    output.write(plaintext)
                final = decryptor.finalize()
                size += len(final)
                digest.update(final)
                output.write(final)
                output.flush()
            if size != plaintext_size or digest.hexdigest() != plaintext_sha256:
                raise TransferRefusal("decrypted transfer identity does not match its seal")
            _publish(descriptor, temporary, output_path)
        except Exception:
            with suppress(OSError):
                os.close(descriptor)
            temporary.unlink(missing_ok=True)
            raise


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="confidential-artifact")
    subparsers = parser.add_subparsers(dest="command", required=True)
    encrypt_parser = subparsers.add_parser("encrypt")
    encrypt_parser.add_argument("--input", type=Path, required=True)
    encrypt_parser.add_argument("--output", type=Path, required=True)
    encrypt_parser.add_argument("--public-key-b64", required=True)
    decrypt_parser = subparsers.add_parser("decrypt")
    decrypt_parser.add_argument("--input", type=Path, required=True)
    decrypt_parser.add_argument("--output", type=Path, required=True)
    decrypt_parser.add_argument("--private-key-stdin", action="store_true", required=True)
    return parser


def main() -> int:
    arguments = _parser().parse_args()
    try:
        if arguments.command == "encrypt":
            encrypt(arguments.input, arguments.output, arguments.public_key_b64)
        else:
            decrypt(arguments.input, arguments.output)
    except TransferRefusal as error:
        print(f"Confidential transfer refused: {error}", file=sys.stderr)
        return 2
    except Exception:
        print("Confidential transfer refused: cryptographic verification failed.", file=sys.stderr)
        return 2
    print(json.dumps({"operation": arguments.command, "status": "passed"}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
