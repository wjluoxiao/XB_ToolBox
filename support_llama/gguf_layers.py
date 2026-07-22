import struct

def read_u32(f):
    return struct.unpack("<I", f.read(4))[0]


def read_u64(f):
    return struct.unpack("<Q", f.read(8))[0]


def read_string(f):
    ln = read_u64(f)
    return f.read(ln).decode("utf-8")


def read_value(f):
    vtype = read_u32(f)

    # GGUF value types
    if vtype == 0:   # uint8
        return struct.unpack("<B", f.read(1))[0]
    if vtype == 1:   # int8
        return struct.unpack("<b", f.read(1))[0]
    if vtype == 2:   # uint16
        return struct.unpack("<H", f.read(2))[0]
    if vtype == 3:   # int16
        return struct.unpack("<h", f.read(2))[0]
    if vtype == 4:   # uint32
        return struct.unpack("<I", f.read(4))[0]
    if vtype == 5:   # int32
        return struct.unpack("<i", f.read(4))[0]
    if vtype == 6:   # float32
        return struct.unpack("<f", f.read(4))[0]
    if vtype == 7:   # bool
        return struct.unpack("<?", f.read(1))[0]
    if vtype == 8:   # string
        return read_string(f)
    if vtype == 9:   # array
        atype = read_u32(f)
        count = read_u64(f)
        return [read_value_of_type(f, atype) for _ in range(count)]
    if vtype == 10:  # uint64
        return struct.unpack("<Q", f.read(8))[0]
    if vtype == 11:  # int64
        return struct.unpack("<q", f.read(8))[0]
    if vtype == 12:  # float64
        return struct.unpack("<d", f.read(8))[0]

    raise ValueError(f"Unknown value type {vtype}")


def read_value_of_type(f, atype):
    # same mapping as above but without extra type code
    if atype == 0:
        return struct.unpack("<B", f.read(1))[0]
    if atype == 1:
        return struct.unpack("<b", f.read(1))[0]
    if atype == 2:
        return struct.unpack("<H", f.read(2))[0]
    if atype == 3:
        return struct.unpack("<h", f.read(2))[0]
    if atype == 4:
        return struct.unpack("<I", f.read(4))[0]
    if atype == 5:
        return struct.unpack("<i", f.read(4))[0]
    if atype == 6:
        return struct.unpack("<f", f.read(4))[0]
    if atype == 7:
        return struct.unpack("<?", f.read(1))[0]
    if atype == 8:
        return read_string(f)
    if atype == 10:
        return struct.unpack("<Q", f.read(8))[0]
    if atype == 11:
        return struct.unpack("<q", f.read(8))[0]
    if atype == 12:
        return struct.unpack("<d", f.read(8))[0]

    raise ValueError(f"Unknown array item type {atype}")

def get_layer_count(path):
    with open(path, "rb") as f:
        if f.read(4) != b"GGUF":
            raise ValueError("This is not a GGUF file!")
            
        version = read_u32(f)
        tensor_count = read_u64(f)
        kv_count = read_u64(f)
        meta = {}
        
        for _ in range(kv_count):
            key = read_string(f)
            value = read_value(f)
            meta[key] = value
            
    for k, v in meta.items():
        if k.lower().endswith(".block_count"):
            return v
    
    print(f"Failed to read metadata: {e}")
    print(f"Try reading the entire GGUF...")
    
    from gguf import GGUFReader
    reader = GGUFReader(path)
    
    try:
        layer_count = reader.get_field("llama.block_count") 
        if layer_count is None:
            for field in reader.fields.values():
                if field.name.endswith(".block_count"):
                    layer_count = field.parts[field.data[0]]
                    break
                
        if layer_count:
            return int(layer_count[0] if isinstance(layer_count, list) else layer_count)
    except Exception as e:
        print(f"Failed to get block_count: {e}")
        
    return None