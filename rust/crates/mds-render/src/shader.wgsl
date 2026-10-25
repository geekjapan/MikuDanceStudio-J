// MMD-style shading: saturate(ambient + diffuse * light), times the texture, an optional sphere
// map (multiply or add) and a toon ramp lookup by the angle to the light, plus a Blinn-Phong
// highlight, and an inverted-hull edge.

struct Scene {
    view_proj: mat4x4<f32>,
    view: mat4x4<f32>,
    eye: vec4<f32>,
    // Direction the light travels, world space; w is 1 when the toon ramp applies, else 0.
    light_dir: vec4<f32>,
    light_color: vec4<f32>,
    // Render target width and height in pixels, then a clip-space shift (x right, y up).
    screen: vec4<f32>,
}

struct Material {
    diffuse: vec4<f32>,
    ambient: vec4<f32>,
    // rgb specular color, w specular power.
    specular: vec4<f32>,
    // y sphere mode (0 none, 1 multiply, 2 add); the rest unused.
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
}

struct EdgeIn {
    @location(0) position: vec3<f32>,
    @location(1) color: vec4<f32>,
}

struct EdgeOut {
    @builtin(position) clip: vec4<f32>,
    @location(0) color: vec4<f32>,
}

struct VsOut {
    @builtin(position) clip: vec4<f32>,
    @location(0) world: vec3<f32>,
    @location(1) normal: vec3<f32>,
    @location(2) uv: vec2<f32>,
}

fn shifted(clip: vec4<f32>) -> vec4<f32> {
    return vec4<f32>(clip.x + scene.screen.z * clip.w, clip.y + scene.screen.w * clip.w, clip.z, clip.w);
}

@vertex
fn vs_main(v: VsIn) -> VsOut {
    var o: VsOut;
    o.clip = shifted(scene.view_proj * vec4<f32>(v.position, 1.0));
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
    var color = clamp(mat.ambient.rgb + mat.diffuse.rgb * lc, vec3<f32>(0.0), vec3<f32>(1.0));
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
    let ramp = textureSampleLevel(toon, samp, vec2<f32>(0.5, 0.5 - 0.5 * ndl), 0.0).rgb;
    color = color * mix(vec3<f32>(1.0), ramp, scene.light_dir.w);

    let power = mat.specular.w;
    if power > 0.0 {
        let to_eye = normalize(scene.eye.xyz - i.world);
        let h = normalize(to_light + to_eye);
        color = color + mat.specular.rgb * lc * pow(max(dot(n, h), 0.0), power);
    }
    return vec4<f32>(clamp(color, vec3<f32>(0.0), vec3<f32>(1.0)), mat.diffuse.a);
}

// Edge: the back faces of the hull that mds-skin pushed out along the normals, colored per vertex.
@vertex
fn vs_edge(v: EdgeIn) -> EdgeOut {
    var o: EdgeOut;
    o.clip = shifted(scene.view_proj * vec4<f32>(v.position, 1.0));
    o.color = v.color;
    return o;
}

@fragment
fn fs_edge(i: EdgeOut) -> @location(0) vec4<f32> {
    return i.color;
}
