use std::fs;
use std::path::Path;

fn decode(c: u8) -> f32 {
    let value = f32::from(c) / 255.0;
    if value <= 0.04045 { value / 12.92 } else { ((value + 0.055) / 1.055).powf(2.4) }
}
fn encode(value: f32, alpha: bool) -> u8 {
    let value = if alpha { value } else if value <= 0.003_130_8 {
        value * 12.92
    } else { 1.055 * value.powf(1.0 / 2.4) - 0.055 };
    (value * 255.0).round().clamp(0.0, 255.0) as u8
}
struct Reader { bytes: Vec<u8>, at: usize }
impl Reader {
    fn new(path: &Path) -> Self { Self { bytes: fs::read(path).expect("read protocol"), at: 0 } }
    fn take(&mut self, n: usize) -> &[u8] {
        let start = self.at; self.at += n; &self.bytes[start..self.at]
    }
    fn word(&mut self) -> u32 { u32::from_le_bytes(self.take(4).try_into().unwrap()) }
    fn end(&self) { assert_eq!(self.at, self.bytes.len(), "protocol trailing bytes"); }
}
fn self_check() {
    for c in 0..=255u8 {
        let mut sum = 0.0f32;
        for _ in 0..8 { sum += decode(c); }
        assert_eq!(encode(sum / 8.0, false), c, "constant color");
        let mut alpha = 0.0f32;
        for _ in 0..8 { alpha += f32::from(c) / 255.0; }
        assert_eq!(encode(alpha / 8.0, true), c, "constant alpha");
    }
    assert_eq!(encode(0.0, true), 0);
    assert_eq!(encode(1.0, true), 255);
    let fold = |values: &[f32]| values.iter().fold(0.0f32, |sum, v| sum + v);
    assert_ne!(fold(&[1.0, 0.00000001, 0.00000001, 0.00000001, 0.00000001, 0.00000001, 0.00000001, 0.00000001]).to_bits(),
        fold(&[0.00000001, 0.00000001, 0.00000001, 0.00000001, 0.00000001, 0.00000001, 0.00000001, 1.0]).to_bits(), "ordered f32 witness");
}
fn main() {
    self_check();
    let args: Vec<_> = std::env::args().collect();
    if args.len() == 2 && args[1] == "--self-check" { println!("REPLAY_SELF_CHECK_OK"); return; }
    assert_eq!(args.len(), 3, "usage: replay CALL_DIRECTORY OUTPUT_RGBA");
    let dir = Path::new(&args[1]);
    let mut header = Reader::new(&dir.join("call.bin"));
    assert_eq!(header.take(8), b"MDSSMP01");
    let len = header.word() as usize;
    let name = std::str::from_utf8(header.take(len)).unwrap().to_owned();
    let ordinal = header.word();
    let width = header.word() as usize;
    let height = header.word() as usize;
    let padded = header.word() as usize;
    let row = header.word() as usize;
    let count = header.word() as usize;
    assert_eq!(count, 8);
    assert_eq!(row, width * 4);
    assert!(padded >= row);
    let pixel_offset = [f32::from_bits(header.word()), f32::from_bits(header.word())];
    let lut: [f32; 256] = std::array::from_fn(|i| decode(i as u8));
    for (i, value) in lut.iter().enumerate() {
        assert_eq!(header.word(), value.to_bits(), "independent decode LUT {i}");
    }
    let offsets: Vec<_> = (0..count).map(|_| [header.word(), header.word()]).collect();
    header.end();
    let mut sum = vec![0.0f32; width * height * 4];
    for (index, offset) in offsets.iter().enumerate() {
        let mut meta = Reader::new(&dir.join(format!("sample-{index}.bin")));
        assert_eq!(meta.word(), index as u32);
        assert_eq!([meta.word(), meta.word()], *offset);
        let shift = [meta.word(), meta.word()];
        for c in 0..2 { assert_eq!(shift[c], (pixel_offset[c] - f32::from_bits(offset[c])).to_bits()); }
        meta.end();
        let raw = fs::read(dir.join(format!("sample-{index}.rgba"))).expect("read sample");
        assert_eq!(raw.len(), sum.len());
        for (i, value) in raw.into_iter().enumerate() {
            sum[i] += if i % 4 == 3 { f32::from(value) / 255.0 } else { lut[value as usize] };
        }
    }
    let mut finish = Reader::new(&dir.join("finish.bin"));
    let points = finish.word();
    for _ in 0..points {
        let x = finish.word() as usize;
        let y = finish.word() as usize;
        assert!(x < width && y < height);
        for c in 0..4 { assert_eq!(finish.word(), sum[(y * width + x) * 4 + c].to_bits(), "actual accumulation at {x},{y},{c}"); }
    }
    assert_eq!(finish.take(8), b"COMPLETE");
    finish.end();
    let rgba: Vec<_> = sum.iter().enumerate().map(|(i, s)| encode(s / count as f32, i % 4 == 3)).collect();
    fs::OpenOptions::new().write(true).create_new(true).open(&args[2])
        .and_then(|mut f| std::io::Write::write_all(&mut f, &rgba)).expect("exclusive replay output");
    println!("REPLAY_OK {name} {ordinal} {width} {height} {points}");
}
