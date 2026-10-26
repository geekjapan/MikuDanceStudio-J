//! The wgpu device, with every validation and internal error collected instead of panicking.

use std::sync::{Arc, Mutex};

pub struct Gpu {
    pub device: wgpu::Device,
    pub queue: wgpu::Queue,
    /// `name|backend`, the key the hash test records under.
    pub adapter: String,
    /// Errors no scope caught (the device's uncaptured-error handler).
    errors: Arc<Mutex<Vec<String>>>,
    pub features: wgpu::Features,
}

/// The optional features the runtime uses when the adapter has them.
const WANTED: wgpu::Features = wgpu::Features::FLOAT32_FILTERABLE
    .union(wgpu::Features::TEXTURE_COMPRESSION_BC)
    .union(wgpu::Features::TEXTURE_FORMAT_16BIT_NORM)
    .union(wgpu::Features::ADDRESS_MODE_CLAMP_TO_BORDER);

impl Gpu {
    /// `Ok(None)` when the host has no adapter.
    pub fn new() -> Result<Option<Gpu>, String> {
        let backends = if cfg!(target_os = "macos") {
            wgpu::Backends::METAL
        } else if cfg!(windows) {
            wgpu::Backends::DX12
        } else {
            wgpu::Backends::VULKAN
        };
        let mut desc = wgpu::InstanceDescriptor::new_without_display_handle();
        desc.backends = backends;
        let instance = wgpu::Instance::new(desc.with_env());
        let Ok(adapter) =
            pollster::block_on(instance.request_adapter(&wgpu::RequestAdapterOptions::default()))
        else {
            return Ok(None);
        };
        let info = adapter.get_info();
        let features = adapter.features() & WANTED;
        let (device, queue) = pollster::block_on(adapter.request_device(&wgpu::DeviceDescriptor {
            label: Some("mds-mmert"),
            required_features: features,
            required_limits: adapter.limits(),
            ..Default::default()
        }))
        .map_err(|e| format!("cannot create a device on {}: {e}", info.name))?;
        let errors = Arc::new(Mutex::new(Vec::new()));
        let sink = errors.clone();
        device.on_uncaptured_error(Arc::new(move |e: wgpu::Error| {
            sink.lock().unwrap().push(e.to_string());
        }));
        Ok(Some(Gpu {
            device,
            queue,
            adapter: format!("{}|{:?}", info.name, info.backend),
            errors,
            features,
        }))
    }

    /// The runtime on a device the caller owns, such as a window's, so that the MME frame is
    /// drawn where the window samples it. The runtime takes the optional features the device
    /// has; it installs no uncaptured-error handler (the device's owner keeps its own), so
    /// [`Gpu::scoped`] reports only what its scopes catch.
    pub fn from_device(device: &wgpu::Device, queue: &wgpu::Queue, adapter: &str) -> Gpu {
        Gpu {
            device: device.clone(),
            queue: queue.clone(),
            adapter: adapter.to_string(),
            errors: Arc::new(Mutex::new(Vec::new())),
            features: device.features() & WANTED,
        }
    }

    /// Runs `f` inside validation and internal error scopes and returns its value with every
    /// error it raised (including uncaptured ones from earlier submissions).
    pub fn scoped<T>(&self, f: impl FnOnce() -> T) -> (T, Vec<String>) {
        let internal = self.device.push_error_scope(wgpu::ErrorFilter::Internal);
        let validation = self.device.push_error_scope(wgpu::ErrorFilter::Validation);
        let v = f();
        let mut errors: Vec<String> = [
            pollster::block_on(validation.pop()),
            pollster::block_on(internal.pop()),
        ]
        .into_iter()
        .flatten()
        .map(|e| e.to_string())
        .collect();
        errors.append(&mut self.errors.lock().unwrap());
        (v, errors)
    }

    pub fn wait(&self) -> Result<(), String> {
        self.device
            .poll(wgpu::PollType::wait_indefinitely())
            .map(|_| ())
            .map_err(|e| format!("poll: {e}"))
    }
}
