import struct, sys, os

def png_size(path):
    with open(path, 'rb') as f:
        head = f.read(24)
    if head[:8] != b'\x89PNG\r\n\x1a\n':
        return None
    w, h = struct.unpack('>II', head[16:24])
    return w, h

def jpeg_size(path):
    with open(path, 'rb') as f:
        data = f.read()
    i = 2
    while i < len(data) - 9:
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i+1]
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            h, w = struct.unpack('>HH', data[i+5:i+9])
            return w, h
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        seg = struct.unpack('>H', data[i+2:i+4])[0]
        i += 2 + seg
    return None

for p in sys.argv[1:]:
    if not os.path.exists(p):
        print('%-52s MISSING' % p)
        continue
    ext = os.path.splitext(p)[1].lower()
    size = jpeg_size(p) if ext in ('.jpg', '.jpeg') else png_size(p)
    kb = os.path.getsize(p) / 1024.0
    if size:
        w, h = size
        print('%-52s %5dx%-5d ratio=%.3f  %7.1f KB' % (p, w, h, w / float(h), kb))
    else:
        print('%-52s UNKNOWN  %7.1f KB' % (p, kb))
