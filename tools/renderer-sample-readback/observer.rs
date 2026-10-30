use std::cell::Cell;
use std::fs::{self, File, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};

thread_local! { static ORDINAL: Cell<u32> = const { Cell::new(0) }; }

fn create(path: &Path) -> Result<File, String> {
    OpenOptions::new().write(true).create_new(true).open(path).map_err(|e| e.to_string())
}
fn words(file: &mut File, values: impl IntoIterator<Item = u32>) -> Result<(), String> {
    for value in values {
        file.write_all(&value.to_le_bytes()).map_err(|e| e.to_string())?;
    }
    Ok(())
}

pub(super) struct Capture {
    dir: PathBuf,
    width: u32,
    height: u32,
    padded: u32,
    row: u32,
    count: u32,
    next: u32,
    points: Vec<(u32, u32)>,
}

impl Capture {
    pub(super) fn begin(frame: &crate::Frame, padded: u32, row: u32, lut: &[f32; 256]) -> Result<Self, String> {
        let thread = std::thread::current();
        let name = thread.name().ok_or("missing libtest thread name")?;
        if name.is_empty() || !name.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'_') {
            return Err("unsafe libtest thread name".into());
        }
        let ordinal = ORDINAL.with(|n| { let value = n.get(); n.set(value + 1); value });
        let root = std::env::var_os("MDS_SAMPLE_READBACK_DIR").ok_or("missing sample output environment")?;
        let dir = PathBuf::from(root).join(format!("{name}-{ordinal}"));
        fs::create_dir(&dir).map_err(|e| e.to_string())?;
        let mut file = create(&dir.join("call.bin"))?;
        file.write_all(b"MDSSMP01").map_err(|e| e.to_string())?;
        words(&mut file, [name.len() as u32])?;
        file.write_all(name.as_bytes()).map_err(|e| e.to_string())?;
        words(&mut file, [ordinal, frame.width, frame.height, padded, row, frame.samples.len() as u32])?;
        words(&mut file, frame.pixel_offset.map(f32::to_bits))?;
        words(&mut file, lut.iter().map(|v| v.to_bits()))?;
        words(&mut file, frame.samples.iter().flat_map(|s| s.map(f32::to_bits)))?;
        let point_path = std::env::var_os("MDS_SAMPLE_POINTS").ok_or("missing points environment")?;
        let text = fs::read_to_string(point_path).map_err(|e| e.to_string())?;
        let mut points = Vec::new();
        for line in text.lines() {
            let fields: Vec<_> = line.split_whitespace().collect();
            if fields.len() != 3 { return Err("invalid point contract".into()); }
            if fields[0] == name {
                let x: u32 = fields[1].parse().map_err(|_| "invalid point x")?;
                let y: u32 = fields[2].parse().map_err(|_| "invalid point y")?;
                if x >= frame.width || y >= frame.height || points.contains(&(x, y)) {
                    return Err("invalid point coordinate".into());
                }
                points.push((x, y));
            }
        }
        Ok(Self { dir, width: frame.width, height: frame.height, padded, row,
            count: frame.samples.len() as u32, next: 0, points })
    }

    pub(super) fn sample(&mut self, sample: [f32; 2], shift: [f32; 2], mapped: &[u8]) -> Result<(), String> {
        if self.next >= self.count || self.row != self.width * 4 || self.padded < self.row ||
            mapped.len() != (self.padded as usize) * (self.height as usize) {
            return Err("invalid mapped sample dimensions/count".into());
        }
        let mut meta = create(&self.dir.join(format!("sample-{}.bin", self.next)))?;
        words(&mut meta, [self.next])?;
        words(&mut meta, sample.map(f32::to_bits))?;
        words(&mut meta, shift.map(f32::to_bits))?;
        let mut raw = create(&self.dir.join(format!("sample-{}.rgba", self.next)))?;
        for row in mapped.chunks_exact(self.padded as usize) {
            raw.write_all(&row[..self.row as usize]).map_err(|e| e.to_string())?;
        }
        self.next += 1;
        Ok(())
    }

    pub(super) fn finish(self, sum: &[f32]) -> Result<(), String> {
        if self.next != self.count || sum.len() != (self.width * self.height * 4) as usize {
            return Err("incomplete sample capture".into());
        }
        let mut file = create(&self.dir.join("finish.bin"))?;
        words(&mut file, [self.points.len() as u32])?;
        for (x, y) in self.points {
            words(&mut file, [x, y])?;
            let i = ((y * self.width + x) * 4) as usize;
            words(&mut file, sum[i..i + 4].iter().map(|v| v.to_bits()))?;
        }
        file.write_all(b"COMPLETE").map_err(|e| e.to_string())?;
        file.sync_all().map_err(|e| e.to_string())
    }
}
