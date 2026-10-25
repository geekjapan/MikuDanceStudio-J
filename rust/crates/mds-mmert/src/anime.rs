//! Animated textures (`ANIMATEDTEXTURE`): GIF and APNG files decoded to frames, and the frame a
//! time selects. Ported from `third_party/mmeffect/src/mmeffect/anime_texture.cpp`
//! (`AnimeObject::FindFrame`, the `AnimeGif` and `AnimePng` constructors, `AnimePng::DecodeFrame`,
//! `MmeAnimeTick`).
//!
//! The C++ decodes through GDI+. Here GIF frames are decoded with `weezl` and composed on a
//! canvas with the GIF disposal methods, as GDI+ selects an active frame; an APNG frame is
//! rebuilt as a standalone PNG the way `AnimePng::DecodeFrame` does, decoded with `png`, and
//! composed with the C++'s dispose and blend rules.

/// The cumulative-start table of `AnimeObject`: when each frame starts within one loop.
#[derive(Clone, Debug, PartialEq)]
pub struct Timeline {
    /// The start of each frame in seconds, frame order.
    pub starts: Vec<f64>,
    /// One loop in seconds.
    pub total: f64,
    /// Loops before the last frame holds; 0 loops forever.
    pub loops: u32,
}

impl Timeline {
    /// The GIF table of the `AnimeGif` constructor: `delays` are the frame delays in
    /// centiseconds (`PropertyTagFrameDelay`); a frame past the table or with no delay lasts
    /// 1/30 s. `loop_count` is `PropertyTagLoopCount` (0xFFFF loops forever).
    pub fn gif(frames: usize, delays: &[u32], loop_count: u32) -> Timeline {
        let (mut acc_ms, mut zero) = (0u64, 0u64);
        let mut starts = Vec::with_capacity(frames);
        for i in 0..frames {
            starts.push(zero as f64 / 30.0 + acc_ms as f64 / 1000.0);
            match delays.get(i) {
                Some(&d) if d != 0 => acc_ms += 10 * u64::from(d),
                _ => zero += 1,
            }
        }
        Timeline {
            starts,
            total: zero as f64 / 30.0 + acc_ms as f64 / 1000.0,
            loops: if loop_count == 0xFFFF { 0 } else { loop_count },
        }
    }

    /// The APNG table of the `AnimePng` constructor from the fcTL delays (numerator,
    /// denominator): a zero denominator is 100, then a zero numerator is 1/30 s. The sum is an
    /// exact fraction until its numerator or denominator reaches 2^48, a double after that.
    pub fn apng(delays: &[(u16, u16)], num_plays: u32) -> Timeline {
        let (mut num, mut den) = (0u64, 1u64);
        let mut acc = 0.0f64;
        let mut overflowed = false;
        let mut starts = Vec::with_capacity(delays.len());
        for &(n, d) in delays {
            let d = if d == 0 { 100 } else { d };
            let (n, d) = if n == 0 { (1, 30) } else { (n, d) };
            starts.push(if overflowed {
                acc
            } else {
                num as f64 / den as f64
            });
            let (n, d) = (u64::from(n), u64::from(d));
            let g = gcd(den, d);
            let new_num = num
                .wrapping_mul(d / g)
                .wrapping_add(n.wrapping_mul(den / g));
            let new_den = (d / g).wrapping_mul(den);
            (num, den) = (new_num, new_den);
            if (new_num | new_den) & 0xFFFF_0000_0000_0000 != 0 {
                overflowed = true;
            }
            acc += n as f64 / d as f64;
        }
        Timeline {
            starts,
            total: if overflowed {
                acc
            } else {
                num as f64 / den as f64
            },
            loops: num_plays,
        }
    }

    /// `AnimeObject::FindFrame`: the frame shown at `time` (seconds), started at `offset` and
    /// played at `speed`.
    pub fn frame(&self, time: f64, offset: f64, speed: f64) -> usize {
        if self.starts.is_empty() {
            return 0;
        }
        let pos = (time - offset) * speed;
        if pos < 0.0 {
            return 0;
        }
        let total = if self.total > 0.0 { self.total } else { 1.0 };
        // cvttsd2si, compared unsigned with the play count.
        let loops = (pos / total) as i32;
        if self.loops != 0 && loops as u32 >= self.loops {
            return self.starts.len() - 1;
        }
        let frac = pos - f64::from(loops) * total;
        self.starts.partition_point(|&s| s <= frac).max(1) - 1
    }
}

fn gcd(mut a: u64, mut b: u64) -> u64 {
    while b != 0 {
        (a, b) = (b, a % b);
    }
    a
}

/// A decoded animated texture: the frames as RGBA8 of `width` x `height`, top row first.
pub struct Anime {
    pub width: u32,
    pub height: u32,
    pub timeline: Timeline,
    source: Source,
}

enum Source {
    /// Every frame composed in advance (an APNG that fits the preload budget).
    Frames(Vec<Vec<u8>>),
    Gif(Box<Gif>),
    /// An APNG composed on demand from the persistent base, as the C++ does past the budget.
    OnDemand(Box<Apng>),
}

impl Anime {
    /// The ctor dispatch of `sub_18000F3A0` case 45 on the last four characters of the name.
    pub fn open(path: &std::path::Path) -> Result<Anime, String> {
        let name = path.to_string_lossy();
        let fail = || format!("failed to open '{name}'\n");
        let bytes = std::fs::read(path).map_err(|_| fail())?;
        let ext = name
            .get(name.len().saturating_sub(4)..)
            .unwrap_or("")
            .to_ascii_lowercase();
        let r = if ext == ".gif" {
            gif(&bytes)
        } else {
            apng(&bytes)
        };
        r.map_err(|generic| {
            if generic {
                fail()
            } else {
                format!("failed to open '{name}': source image must be animated\n")
            }
        })
    }

    /// The RGBA8 pixels of `frame` (`SetFrame` then `GetTexture`).
    pub fn pixels(&mut self, frame: usize) -> &[u8] {
        match &mut self.source {
            Source::Frames(f) => &f[frame.min(f.len() - 1)],
            Source::Gif(g) => g.compose(frame),
            Source::OnDemand(a) => {
                a.compose(frame);
                &a.upload
            }
        }
    }
}

/// `Err(true)` the generic open failure, `Err(false)` "source image must be animated".
type Decoded = Result<Anime, bool>;

fn u16le(b: &[u8], i: usize) -> Option<u16> {
    Some(u16::from_le_bytes(b.get(i..i + 2)?.try_into().ok()?))
}

/// The data of the sub-blocks at `pos`, and the position after the terminator.
fn sub_blocks(b: &[u8], mut pos: usize) -> Option<(Vec<Vec<u8>>, usize)> {
    let mut out = Vec::new();
    loop {
        let n = usize::from(*b.get(pos)?);
        pos += 1;
        if n == 0 {
            return Some((out, pos));
        }
        out.push(b.get(pos..pos + n)?.to_vec());
        pos += n;
    }
}

struct GifFrame {
    rect: (usize, usize, usize, usize),
    pixels: Vec<Option<[u8; 4]>>,
    dispose: u8,
    delay: u32,
}

fn gif(b: &[u8]) -> Decoded {
    if !(b.starts_with(b"GIF87a") || b.starts_with(b"GIF89a")) {
        return Err(true);
    }
    let (w, h) = (
        usize::from(u16le(b, 6).ok_or(true)?),
        usize::from(u16le(b, 8).ok_or(true)?),
    );
    let flags = *b.get(10).ok_or(true)?;
    let palette = |at: usize, flags: u8| -> Option<(Vec<[u8; 3]>, usize)> {
        if flags & 0x80 == 0 {
            return Some((Vec::new(), at));
        }
        let n = 2usize << (flags & 7);
        let raw = b.get(at..at + 3 * n)?;
        Some((
            raw.chunks(3).map(|c| [c[0], c[1], c[2]]).collect(),
            at + 3 * n,
        ))
    };
    let (global, mut pos) = palette(13, flags).ok_or(true)?;
    let (mut gce, mut loop_count) = (None::<(u8, bool, u32, u8)>, 0u32);
    let mut frames = Vec::new();
    while let Some(&tag) = b.get(pos) {
        match tag {
            0x21 => {
                let label = *b.get(pos + 1).ok_or(true)?;
                let (blocks, next) = sub_blocks(b, pos + 2).ok_or(true)?;
                match (label, blocks.first()) {
                    (0xF9, Some(g)) if g.len() >= 4 => {
                        let delay = u32::from(u16le(g, 1).ok_or(true)?);
                        gce = Some(((g[0] >> 2) & 7, g[0] & 1 != 0, delay, g[3]));
                    }
                    (0xFF, Some(app)) if app.as_slice() == b"NETSCAPE2.0" => {
                        if let Some(s) = blocks.get(1).filter(|s| s.len() >= 3 && s[0] == 1) {
                            loop_count = u32::from(u16::from_le_bytes([s[1], s[2]]));
                        }
                    }
                    _ => {}
                }
                pos = next;
            }
            0x2C => {
                let field = |i| u16le(b, pos + i).map(usize::from).ok_or(true);
                let (x, y, fw, fh) = (field(1)?, field(3)?, field(5)?, field(7)?);
                let flags = *b.get(pos + 9).ok_or(true)?;
                let (local, next) = palette(pos + 10, flags).ok_or(true)?;
                let min = *b.get(next).ok_or(true)?;
                let (data, next) = sub_blocks(b, next + 1).ok_or(true)?;
                pos = next;
                let mut indices = Vec::new();
                let _ = weezl::decode::Decoder::new(weezl::BitOrder::Lsb, min.clamp(1, 11))
                    .into_vec(&mut indices)
                    .decode(&data.concat());
                indices.resize(fw * fh, 0);
                if flags & 0x40 != 0 {
                    let rows: Vec<usize> = (0..fh)
                        .step_by(8)
                        .chain((4..fh).step_by(8))
                        .chain((2..fh).step_by(4))
                        .chain((1..fh).step_by(2))
                        .collect();
                    let mut out = vec![0; fw * fh];
                    for (src, &dst) in rows.iter().enumerate() {
                        out[dst * fw..(dst + 1) * fw]
                            .copy_from_slice(&indices[src * fw..(src + 1) * fw]);
                    }
                    indices = out;
                }
                let colors = if local.is_empty() { &global } else { &local };
                let (dispose, transparent, delay, key) = gce.take().unwrap_or((0, false, 0, 0));
                let pixels = indices
                    .iter()
                    .map(|&i| {
                        if transparent && i == key {
                            return None;
                        }
                        let c = colors.get(usize::from(i)).copied().unwrap_or([0; 3]);
                        Some([c[0], c[1], c[2], 255])
                    })
                    .collect();
                frames.push(GifFrame {
                    rect: (x, y, fw, fh),
                    pixels,
                    dispose,
                    delay,
                });
            }
            _ => break,
        }
    }
    if frames.len() <= 1 {
        return Err(frames.is_empty());
    }
    let delays: Vec<u32> = frames.iter().map(|f| f.delay).collect();
    Ok(Anime {
        width: w as u32,
        height: h as u32,
        timeline: Timeline::gif(frames.len(), &delays, loop_count),
        source: Source::Gif(Box::new(Gif {
            frames,
            width: w,
            height: h,
            canvas: vec![0; w * h * 4],
            saved: Vec::new(),
            current: None,
        })),
    })
}

/// A GIF composed on demand: the canvas after `current`, and the canvas before it for a
/// "restore to previous" disposal. Going backwards recomposes from the first frame.
struct Gif {
    frames: Vec<GifFrame>,
    width: usize,
    height: usize,
    canvas: Vec<u8>,
    saved: Vec<u8>,
    current: Option<usize>,
}

impl Gif {
    fn compose(&mut self, frame: usize) -> &[u8] {
        let (w, h) = (self.width, self.height);
        let frame = frame.min(self.frames.len() - 1);
        if self.current.is_some_and(|c| c > frame) {
            self.current = None;
            self.canvas.fill(0);
        }
        let start = self.current.map_or(0, |c| c + 1);
        for i in start..=frame {
            if let Some(p) = i.checked_sub(1).map(|p| &self.frames[p]) {
                match p.dispose {
                    2 => fill(&mut self.canvas, w, h, p.rect, [0; 4]),
                    3 => std::mem::swap(&mut self.canvas, &mut self.saved),
                    _ => {}
                }
            }
            let f = &self.frames[i];
            if f.dispose == 3 {
                self.saved.clone_from(&self.canvas);
            }
            let (x, y, fw, _) = f.rect;
            for (k, px) in f.pixels.iter().enumerate() {
                let (cx, cy) = (x + k % fw.max(1), y + k / fw.max(1));
                if let (Some(px), true) = (px, cx < w && cy < h) {
                    self.canvas[(cy * w + cx) * 4..][..4].copy_from_slice(px);
                }
            }
        }
        self.current = Some(frame);
        &self.canvas
    }
}

fn fill(
    canvas: &mut [u8],
    w: usize,
    h: usize,
    (x, y, fw, fh): (usize, usize, usize, usize),
    c: [u8; 4],
) {
    for cy in y..(y + fh).min(h) {
        for cx in x..(x + fw).min(w) {
            canvas[(cy * w + cx) * 4..][..4].copy_from_slice(&c);
        }
    }
}

fn be32(b: &[u8], i: usize) -> Option<u32> {
    Some(u32::from_be_bytes(b.get(i..i + 4)?.try_into().ok()?))
}

struct FrameRec {
    /// The offset of the chunk after the frame's fcTL.
    data: usize,
    w: u32,
    h: u32,
    x: u32,
    y: u32,
    dispose: u8,
    blend: u8,
}

/// `AnimePng`: the chunks before the first frame, the frames, and the persistent base.
struct Apng {
    file: Vec<u8>,
    chunks: Vec<(u32, Vec<u8>)>,
    frames: Vec<FrameRec>,
    width: u32,
    height: u32,
    base: Vec<u8>,
    upload: Vec<u8>,
    current: Option<usize>,
}

fn apng(b: &[u8]) -> Decoded {
    if !b.starts_with(b"\x89PNG\r\n\x1a\n") {
        return Err(true);
    }
    let (mut pos, mut finalized) = (8, false);
    let (mut width, mut height, mut num_frames, mut num_plays) = (0, 0, 0u32, 0u32);
    let (mut chunks, mut frames, mut delays) = (Vec::new(), Vec::new(), Vec::new());
    while let (Some(len), Some(ty)) = (be32(b, pos), be32(b, pos + 4)) {
        let body = pos + 8;
        let end = body + len as usize + 4;
        let Some(data) = b.get(body..end) else {
            break;
        };
        pos = end;
        match &ty.to_be_bytes() {
            b"IDAT" | b"fdAT" => {}
            b"IEND" => {
                finalized = true;
                break;
            }
            b"acTL" => {
                if len >= 8 {
                    (num_frames, num_plays) = (be32(data, 0).unwrap(), be32(data, 4).unwrap());
                }
            }
            b"fcTL" => {
                if len >= 26 {
                    let d = |i| be32(data, i).unwrap();
                    delays.push((
                        u16::from_be_bytes([data[20], data[21]]),
                        u16::from_be_bytes([data[22], data[23]]),
                    ));
                    frames.push(FrameRec {
                        data: pos,
                        w: d(4),
                        h: d(8),
                        x: d(12),
                        y: d(16),
                        dispose: data[24],
                        blend: data[25],
                    });
                }
            }
            _ => {
                if ty == u32::from_be_bytes(*b"IHDR") && len >= 8 {
                    (width, height) = (be32(data, 0).unwrap(), be32(data, 4).unwrap());
                }
                chunks.push((ty, data.to_vec()));
            }
        }
    }
    if !finalized || num_frames as usize != frames.len() || width == 0 || height == 0 {
        return Err(true);
    }
    if num_frames == 0 {
        return Err(false);
    }
    let size = (width * height * 4) as usize;
    let mut a = Apng {
        file: b.to_vec(),
        chunks,
        frames,
        width,
        height,
        base: vec![0; size],
        upload: vec![0; size],
        current: None,
    };
    let timeline = Timeline::apng(&delays, num_plays);
    let source = if 4 * u64::from(num_frames) * u64::from(width) * u64::from(height) <= 0xA0_0000 {
        let mut all = Vec::with_capacity(a.frames.len());
        for i in 0..a.frames.len() {
            if !a.compose(i) {
                return Err(true);
            }
            all.push(a.upload.clone());
        }
        Source::Frames(all)
    } else {
        Source::OnDemand(Box::new(a))
    };
    Ok(Anime {
        width,
        height,
        timeline,
        source,
    })
}

/// Source-over of non-premultiplied RGBA8.
fn over(dst: &mut [u8], src: &[u8]) {
    let sa = u32::from(src[3]);
    let da = u32::from(dst[3]) * (255 - sa) / 255;
    let a = sa + da;
    if a == 0 {
        dst.copy_from_slice(&[0; 4]);
        return;
    }
    for c in 0..3 {
        dst[c] = ((u32::from(src[c]) * sa + u32::from(dst[c]) * da) / a) as u8;
    }
    dst[3] = a as u8;
}

fn draw(dst: &mut [u8], dw: u32, dh: u32, tile: &[u8], f: &FrameRec, source_over: bool) {
    for ty in 0..f.h {
        for tx in 0..f.w {
            let (x, y) = (f.x + tx, f.y + ty);
            if x >= dw || y >= dh {
                continue;
            }
            let s = &tile[((ty * f.w + tx) * 4) as usize..][..4];
            let d = &mut dst[((y * dw + x) * 4) as usize..][..4];
            if source_over {
                over(d, s);
            } else {
                d.copy_from_slice(s);
            }
        }
    }
}

impl Apng {
    /// `AnimePng::DecodeFrame`: rebuild frame `i` as a PNG (IHDR sized to the frame, the cached
    /// chunks, the frame's IDAT or fdAT run as IDAT), decode it, and compose it.
    fn compose(&mut self, i: usize) -> bool {
        if self.current == Some(i) {
            return true;
        }
        let Some(f) = self.frames.get(i) else {
            return false;
        };
        let mut png = b"\x89PNG\r\n\x1a\n".to_vec();
        let mut chunk = |ty: &[u8; 4], data: &[u8]| {
            png.extend((data.len() as u32).to_be_bytes());
            png.extend(ty);
            png.extend(data);
            png.extend([0; 4]);
        };
        for (k, (ty, blob)) in self.chunks.iter().enumerate() {
            let mut data = blob[..blob.len() - 4].to_vec();
            if k == 0 && data.len() >= 8 {
                data[..4].copy_from_slice(&f.w.to_be_bytes());
                data[4..8].copy_from_slice(&f.h.to_be_bytes());
            }
            chunk(&ty.to_be_bytes(), &data);
        }
        let mut pos = f.data;
        while let (Some(len), Some(ty)) = (be32(&self.file, pos), be32(&self.file, pos + 4)) {
            let Some(data) = self.file.get(pos + 8..pos + 8 + len as usize) else {
                return false;
            };
            pos += 12 + len as usize;
            match &ty.to_be_bytes() {
                b"fcTL" | b"IEND" => break,
                b"IDAT" => chunk(b"IDAT", data),
                b"fdAT" if len >= 4 => chunk(b"IDAT", &data[4..]),
                _ => {}
            }
        }
        chunk(b"IEND", &[]);
        let Some(tile) = crate::resource::decode_png_rgba(&png, true) else {
            return false;
        };
        if tile.0 != f.w || tile.1 != f.h {
            return false;
        }
        if i == 0 {
            self.base.fill(0);
        }
        let (w, h) = (self.width, self.height);
        if f.dispose <= 1 {
            draw(&mut self.base, w, h, &tile.2, f, f.blend == 1);
        }
        self.upload.copy_from_slice(&self.base);
        if f.dispose == 2 {
            draw(&mut self.upload, w, h, &tile.2, f, f.blend == 1);
        }
        if f.dispose == 1 {
            let rect = (f.x as usize, f.y as usize, f.w as usize, f.h as usize);
            fill(&mut self.base, w as usize, h as usize, rect, [0; 4]);
        }
        self.current = Some(i);
        true
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn find_frame_follows_the_cpp_walk() {
        // 10 cs, none (1/30 s), 20 cs: starts 0, 0.1, 0.1 + 1/30; one loop 0.3 + 1/30 s.
        let t = Timeline::gif(3, &[10, 0, 20], 0xFFFF);
        assert_eq!(t.loops, 0);
        assert_eq!(t.starts[1], 0.1);
        assert_eq!(t.frame(-1.0, 0.0, 1.0), 0);
        assert_eq!(t.frame(0.1, 0.0, 1.0), 1);
        assert_eq!(t.frame(0.0999, 0.0, 1.0), 0);
        assert_eq!(t.frame(0.2, 0.0, 1.0), 2);
        assert_eq!(t.frame(t.total + 0.05, 0.0, 1.0), 0);
        // Offset and speed: (1.15 - 1.0) * 2 = 0.3 is in the third frame.
        assert_eq!(t.frame(1.15, 1.0, 2.0), 2);
        let once = Timeline::gif(3, &[10], 1);
        assert_eq!(once.frame(once.total * 1.5, 0.0, 1.0), 2);
        assert_eq!(once.frame(0.12, 0.0, 1.0), 1);
        // 1/10 + 1/30 is 2/15 exactly; the double sum would be one ulp off.
        let a = Timeline::apng(&[(1, 10), (0, 0), (5, 0)], 3);
        assert_eq!(a.starts, [0.0, 0.1, 2.0 / 15.0]);
        assert_eq!(a.total, 11.0 / 60.0);
        assert_eq!(a.loops, 3);
    }
}
