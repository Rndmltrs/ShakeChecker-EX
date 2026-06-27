def parse_coord(v: float, max_val: int) -> int:
    """Parse coordinate:
    - [0.0, 1.0]: fraction of max_val
    - > 1.0: absolute pixels from 0 (top/left)
    - <= -1.0: absolute pixels from max_val (bottom/right)
    - (-1.0, 0.0): fractional distance from max_val
    """
    if v < 0:
        return max_val + int(v) if v <= -1.0 else max_val + int(max_val * v)
    return int(v) if v > 1.0 else int(max_val * v)
