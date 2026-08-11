#!/usr/bin/env python3
"""Contract-address integrity checker for the KHACN project.

Guards against the attack class this project's README already warns about:
a change that swaps the official KHACN contract address (or the official
symbol / name / website) for a look-alike, in any file that publishes the
project's token identity.

Works across every repo in the KharYsma ecosystem: point it at a repo root
and it scans that tree. Any Ethereum-style address it finds must match the
one official contract, or it fails.

No third-party dependencies. Keccak-256 and the EIP-55 checksum are
implemented from scratch in keccak.py and self-tested against published
known-answer vectors before this script trusts them for anything.

Exit code 0 -> every address found matches the official contract.
Exit code 1 -> a substitution, a malformed address, or a bad field was found.

Usage:
    python3 tools/verify_integrity.py                 # scan this repo
    python3 tools/verify_integrity.py /path/to/repo   # scan another repo
    python3 tools/verify_integrity.py repo1 repo2     # scan several
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from keccak import eip55_checksum, keccak256  # noqa: E402

# --- Canonical, official KHACN identity. Any divergence found in a scanned
# --- tree is treated as a possible substitution attack.
CANONICAL_ADDRESS = "0x11c1b94294A7967092F747434dEE4876EcA5fD53"
CANONICAL_SYMBOL = "KHACN"
CANONICAL_NAME = "KharYsma Coins"
CANONICAL_CHAIN_ID = 1
CANONICAL_WEBSITE = "https://startarcoins.com"

# --- Solana deployment (official fork, live since 11 August 2026).
# --- Same project, same logo, a DIFFERENT chain and a DIFFERENT total supply.
CANONICAL_SOLANA_ADDRESS = "3dhbW1cBcyLddaJXDrY6fP45xfgap45qoCfnaTMCpump"
CANONICAL_SOLANA_WEBSITE = "https://startarcoins.com/solana.html"

ADDRESS_RE = re.compile(r"0x[0-9a-fA-F]{40}")

# Solana mint addresses are base58-encoded 32-byte public keys. A loose base58
# regex would also match git SHAs and random identifiers, so a candidate only
# counts as a Solana address once it decodes to EXACTLY 32 bytes. That check,
# not the regex, is what makes the detection precise.
_B58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
SOLANA_RE = re.compile(r"\b[1-9A-HJ-NP-Za-km-z]{32,44}\b")

# Extensions worth scanning: anything that can publish the token identity.
SCAN_SUFFIXES = {".md", ".json", ".txt", ".html", ".yml", ".yaml"}
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv"}


def self_test_crypto():
    """Refuse to trust the from-scratch Keccak implementation without proof."""
    vectors = [
        "0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed",
        "0xfB6916095ca1df60bB79Ce92cE3Ea74c37c5d359",
        "0xdbF03B407c01E7cD3CBea99509d93f8DDDC8C6FB",
        "0xD1220A0cf47c7B9Be7A2E6BA89F429762e7b9aDb",
    ]
    for v in vectors:
        if eip55_checksum(v[2:]) != v:
            raise RuntimeError(
                "Keccak-256/EIP-55 self-test FAILED on published vector %s. "
                "Refusing to run integrity checks with unverified crypto." % v
            )
    if keccak256(b"a") == keccak256(b"b"):
        raise RuntimeError("Keccak-256 self-test FAILED: collision on trivial inputs.")


def iter_scannable_files(repo_root):
    for path in sorted(repo_root.rglob("*")):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix.lower() in SCAN_SUFFIXES:
            yield path


def check_address(rel_path, address, critical, warnings):
    if address == CANONICAL_ADDRESS:
        return
    try:
        checksummed = eip55_checksum(address[2:])
    except Exception as exc:  # noqa: BLE001
        critical.append(f"{rel_path}: malformed address-like string {address!r} ({exc})")
        return
    if address.lower() == CANONICAL_ADDRESS.lower():
        # Same contract, non-canonical casing (e.g. a lowercase explorer URL).
        # Not an attack -> notice only, does not fail the check.
        warnings.append(
            f"{rel_path}: {address} is the official contract but not in EIP-55 "
            f"casing (recommended: {CANONICAL_ADDRESS})"
        )
    else:
        critical.append(
            f"{rel_path}: address {address} (checksum {checksummed}) is NOT the official "
            f"KHACN contract {CANONICAL_ADDRESS} — possible substitution attempt."
        )


def b58decode(text):
    """Decode base58. Returns bytes, or None when the input is not base58."""
    n = 0
    for ch in text:
        idx = _B58_ALPHABET.find(ch)
        if idx < 0:
            return None
        n = n * 58 + idx
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big") if n else b""
    return b"\x00" * (len(text) - len(text.lstrip("1"))) + raw


def is_solana_pubkey(text):
    """True only when text decodes to exactly 32 bytes — a real Solana pubkey."""
    raw = b58decode(text)
    return raw is not None and len(raw) == 32


def check_solana_address(rel_path, address, critical):
    """Any 32-byte base58 key in the tree must be the official KHACN mint."""
    if address == CANONICAL_SOLANA_ADDRESS:
        return
    critical.append(
        f"{rel_path}: Solana address {address} is NOT the official KHACN mint "
        f"{CANONICAL_SOLANA_ADDRESS} — possible substitution attempt."
    )


def self_test_solana():
    """Prove the base58 decoder before trusting it, same rule as the Keccak side."""
    if not is_solana_pubkey(CANONICAL_SOLANA_ADDRESS):
        raise RuntimeError(
            "Base58 self-test FAILED: the pinned Solana address does not decode "
            "to a 32-byte public key. Refusing to run."
        )
    # A well-known 32-byte system address must also decode cleanly.
    if not is_solana_pubkey("So11111111111111111111111111111111111111112"):
        raise RuntimeError("Base58 self-test FAILED on the wrapped-SOL mint.")
    # A git SHA must NOT be mistaken for a Solana key.
    if is_solana_pubkey("a1cf2d3ad71d059cb4670e4c176cf14bc8fc9d61b19d"):
        raise RuntimeError("Base58 self-test FAILED: git-SHA-like string accepted.")


def check_metadata_fields(path, rel_path, critical):
    """If this file is KHACN token metadata, its identity fields must match."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        critical.append(f"{rel_path}: invalid JSON ({exc})")
        return
    if not isinstance(data, dict):
        return

    # KHACN lives on two chains, so the expected identity depends on which one
    # this file describes. A Solana metadata file legitimately carries a base58
    # mint and its own site; validating it against the Ethereum values would be
    # a false positive.
    is_solana = (
        str(data.get("chain", "")).lower() == "solana"
        or "solana" in str(data.get("network", "")).lower()
        or is_solana_pubkey(str(data.get("address", "")))
    )

    if is_solana:
        expected = {
            "symbol": CANONICAL_SYMBOL,
            "name": CANONICAL_NAME,
            "address": CANONICAL_SOLANA_ADDRESS,
            "website": CANONICAL_SOLANA_WEBSITE,
        }
    else:
        expected = {
            "symbol": CANONICAL_SYMBOL,
            "name": CANONICAL_NAME,
            "chainId": CANONICAL_CHAIN_ID,
            "address": CANONICAL_ADDRESS,
            "website": CANONICAL_WEBSITE,
        }

    # Only enforce on objects that actually claim to describe KHACN, so an
    # unrelated JSON file in the tree is not falsely flagged.
    claims_khacn = str(data.get("symbol", "")).upper() == CANONICAL_SYMBOL or "address" in data
    if not claims_khacn:
        return

    for key, want in expected.items():
        if key not in data:
            continue
        got = data[key]
        same = got.lower() == want.lower() if isinstance(got, str) and isinstance(want, str) else got == want
        if not same:
            critical.append(f"{rel_path}: field '{key}' = {got!r}, expected {want!r}")


def scan_repo(repo_root, critical, warnings):
    repo_root = Path(repo_root).resolve()
    if not repo_root.is_dir():
        critical.append(f"{repo_root}: not a directory")
        return 0, 0

    files_scanned = 0
    addresses_found = 0
    for path in iter_scannable_files(repo_root):
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        files_scanned += 1
        rel = f"{repo_root.name}/{path.relative_to(repo_root)}"

        for addr in sorted(set(ADDRESS_RE.findall(text))):
            addresses_found += 1
            check_address(rel, addr, critical, warnings)

        for cand in sorted(set(SOLANA_RE.findall(text))):
            if is_solana_pubkey(cand):
                addresses_found += 1
                check_solana_address(rel, cand, critical)

        if path.suffix.lower() == ".json":
            check_metadata_fields(path, rel, critical)

    print(f"  scanned {files_scanned} file(s) in {repo_root}")
    return files_scanned, addresses_found


def main(argv):
    self_test_crypto()
    print("[ok] Keccak-256 / EIP-55 self-test passed (4/4 published vectors)")
    self_test_solana()
    print("[ok] base58 / Solana self-test passed (pubkey, wSOL, git-SHA rejection)")

    if eip55_checksum(CANONICAL_ADDRESS[2:]) != CANONICAL_ADDRESS:
        print("[FATAL] pinned CANONICAL_ADDRESS is not valid EIP-55.")
        return 1
    print(f"[ok] official contract is valid EIP-55: {CANONICAL_ADDRESS}\n")

    roots = argv[1:] or [Path(__file__).resolve().parent.parent]

    critical, warnings = [], []
    total_addresses = 0
    for root in roots:
        _, found = scan_repo(root, critical, warnings)
        total_addresses += found

    print()
    if warnings:
        print("Notices (non-blocking):")
        for w in warnings:
            print(f"  ! {w}")
        print()

    if critical:
        print("INTEGRITY CHECK FAILED:\n")
        for c in critical:
            print(f"  - {c}")
        print(f"\n{len(critical)} critical issue(s). Official contract must be exactly:")
        print(f"  {CANONICAL_ADDRESS}")
        return 1

    print(f"[ok] {total_addresses} address reference(s) checked, all official.")
    print("INTEGRITY CHECK PASSED.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
