// MMD-style shading: material colors, a toon ramp lookup, an optional sphere map
// (multiply or add), a Blinn-Phong highlight, and an inverted-hull edge.

struct Scene {
    view_proj: mat4x4<f32>,
    view: mat4x4<f32>,
    eye: vec4<f32>,
    // Direction the light travels, world space.
    light_dir: vec4<f32>,
    light_color: vec4<f32>,
    // Render target width and height in pixels.
    screen: vec4<f32>,
}

struct Material {
    diffuse: vec4<f32>,
    ambient: vec4<f32>,
    // rgb specular color, w specular power.
    specular: vec4<f32>,
    edge_color: vec4<f32>,
    // x edge size in pixels, y sphere mode (0 none, 1 multiply, 2 add), z unused, w unused.
    params: vec4<f32>,
}

@group(0) @binding(0) var<uniform> scene: Scene;
@group(1) @binding(0) var<uniform> mat: Material;
@group(1) @binding(1) var tex: texture_2d<f32>;
@group(1) @binding(2) var sphere: texture_2d<f32>;
@group(1) @binding(3) var toon: texture_2d<f32>;
@group(1) @binding(4) var samp: sampler;

struct VsIn {
    @location(0) position: vec3<f32>,
    @location(1) normal: vec3<f32>,
    @location(2) uv: vec2<f32>,
    @location(3) edge_scale: f32,
}

struct VsOut {
    @builtin(position) clip: vec4<f32>,
    @location(0) world: vec3<f32>,
    @location(1) normal: vec3<f32>,
    @location(2) uv: vec2<f32>,
}

@vertex
fn vs_main(v: VsIn) -> VsOut {
    var o: VsOut;
    o.clip = scene.view_proj * vec4<f32>(v.position, 1.0);
    o.world = v.position;
    o.normal = v.normal;
    o.uv = v.uv;
    return o;
}

@fragment
fn fs_main(i: VsOut, @builtin(front_facing) front: bool) -> @location(0) vec4<f32> {
    var n = normalize(i.normal);
    if !front {
        n = -n;
    }
    let to_light = -normalize(scene.light_dir.xyz);
    let lc = scene.light_color.rgb;
    var color = clamp(mat.diffuse.rgb * lc + mat.ambient.rgb * lc, vec3<f32>(0.0), vec3<f32>(1.0));
    color = color * textureSampleLevel(tex, samp, i.uv, 0.0).rgb;

    let view_n = (scene.view * vec4<f32>(n, 0.0)).xy;
    let sphere_uv = vec2<f32>(view_n.x * 0.5 + 0.5, 0.5 - view_n.y * 0.5);
    let s = textureSampleLevel(sphere, samp, sphere_uv, 0.0).rgb;
    if mat.params.y == 1.0 {
        color = color * s;
    } else if mat.params.y == 2.0 {
        color = color + s;
    }

    // The toon ramp has the lit end at v = 0.
    let ndl = dot(n, to_light);
    color = color * textureSampleLevel(toon, samp, vec2<f32>(0.5, 0.5 - 0.5 * ndl), 0.0).rgb;

    let power = mat.specular.w;
    if power > 0.0 {
        let to_eye = normalize(scene.eye.xyz - i.world);
        let h = normalize(to_light + to_eye);
        color = color + mat.specular.rgb * lc * pow(max(dot(n, h), 0.0), power);
    }
    return vec4<f32>(clamp(color, vec3<f32>(0.0), vec3<f32>(1.0)), mat.diffuse.a);
}

// Edge: the back faces pushed out along the normal by a fixed number of pixels.
@vertex
fn vs_edge(v: VsIn) -> VsOut {
    var o: VsOut;
    var clip = scene.view_proj * vec4<f32>(v.position, 1.0);
    let n = (scene.view_proj * vec4<f32>(v.normal, 0.0)).xy;
    let len = length(n);
    if len > 0.0 {
        let px = mat.params.x * v.edge_scale;
        clip = vec4<f32>(clip.xy + n / len * px * 2.0 / scene.screen.xy * clip.w, clip.zw);
    }
    o.clip = clip;
    o.world = v.position;
    o.normal = v.normal;
    o.uv = v.uv;
    return o;
}

@fragment
fn fs_edge(i: VsOut) -> @location(0) vec4<f32> {
    return mat.edge_color;
}
