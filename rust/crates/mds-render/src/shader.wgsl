// MMD-style shading: saturate(ambient + diffuse * light), times the texture, an optional sphere
// map (multiply or add) and a toon ramp lookup by the angle to the light, plus a Blinn-Phong
// highlight, and an inverted-hull edge.

struct Scene {
    view_proj: mat4x4<f32>,
    view: mat4x4<f32>,
    eye: vec4<f32>,
    // Direction the light travels, world space; w is the toon: 0 none, 1 the toon texture looked
    // up by the angle to the light, 2 the self-shadow blend toward the toon's shadow color.
    light_dir: vec4<f32>,
    light_color: vec4<f32>,
    // Render target width and height in pixels, then a clip-space shift (x right, y up).
    screen: vec4<f32>,
    // The ground shadow color and alpha.
    ground_shadow: vec4<f32>,
    // x: the height the ground shadow is lifted to; yz: the multisample position this
    // render stands for, in pixels from the pixel center (y down); w unused.
    ground_shadow_plane: vec4<f32>,
    // Self-shadow: the light view projection of a scene point (`view::self_shadow_matrices`).
    light_view_proj: mat4x4<f32>,
    // x: 1 when the self-shadow map applies; y: the depth difference factor; z: 1 when the factor
    // is also scaled by the map's v (mode 2, `parthf`); w: the map's size in texels.
    self_shadow: vec4<f32>,
    // The self-shadow map display: left, top, right, bottom in output pixels.
    display: vec4<f32>,
}

struct Material {
    diffuse: vec4<f32>,
    ambient: vec4<f32>,
    // rgb specular color, w specular power.
    specular: vec4<f32>,
    // x 1 when the texture slot has an image, y sphere mode (0 none, 1 multiply, 2 add), z 1 when
    // the material receives the self-shadow; w unused.
    params: vec4<f32>,
    // Accessories only.
    emissive: vec4<f32>,
}

@group(0) @binding(0) var<uniform> scene: Scene;
@group(0) @binding(1) var shadow_map: texture_depth_2d;
@group(1) @binding(0) var<uniform> mat: Material;
@group(1) @binding(1) var tex: texture_2d<f32>;
@group(1) @binding(2) var sphere: texture_2d<f32>;
@group(1) @binding(3) var toon: texture_2d<f32>;
@group(1) @binding(4) var samp: sampler;
@group(1) @binding(5) var clamped: sampler;

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
    // Self-shadow off: the highlight, lit per vertex.
    @location(3) specular: vec3<f32>,
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
    o.specular = vertex_specular(v.position, v.normal);
    return o;
}

// The highlight of Direct3D 9's fixed-function lighting, per vertex: a local viewer, none where the
// vertex faces away from the light, saturated. The skinned normal is used as it is, not
// renormalized (it is shorter than 1 where BDEF2 blends two bone rotations). Fitted to golden2
// `groundshadow-*.png` and `skin-*.png`: the renormalized normal leaves the curled chain up to 8
// levels too bright, a per-pixel highlight up to 6 too dark there and 20 on the skin faces.
fn vertex_specular(p: vec3<f32>, n: vec3<f32>) -> vec3<f32> {
    let power = mat.specular.w;
    let to_light = -normalize(scene.light_dir.xyz);
    if power <= 0.0 || dot(n, to_light) <= 0.0 {
        return vec3<f32>(0.0);
    }
    let h = normalize(to_light + normalize(scene.eye.xyz - p));
    let s = mat.specular.rgb * scene.light_color.rgb * pow(max(dot(n, h), 0.0), power);
    return clamp(s, vec3<f32>(0.0), vec3<f32>(1.0));
}

// The texture coordinate at the pixel center. A multisampled target shades a pixel once, at its
// center, for all its samples; `render_frame` draws one render per sample instead, so it takes
// the texture back to the center (golden2 `accessory-*.png`: the cube's checker is as sharp as one
// lookup per pixel).
fn center_uv(uv: vec2<f32>, q: f32) -> vec2<f32> {
    let o = scene.ground_shadow_plane.yz;
    let n = uv * q;
    let numerator = n - dpdx(n) * o.x - dpdy(n) * o.y;
    let denominator = q - dpdx(q) * o.x - dpdy(q) * o.y;
    return numerator / denominator;
}

// How lit a point is under self-shadow, 1 lit to 0 in shadow, from the depth the shadow map holds
// where the point projects. Outside the map nothing is shadowed. The depth is filtered between
// the four nearest texels (golden2 `selfshadow-*.png` shows no texel steps on the models; 0.996
// and 0.995 within 4 against 0.991 and 0.990 with the nearest texel). The comparison `1 - saturate(max(z - map, 0) * k - 0.3)`, with k 1500 in mode 1 and
// 8000 times the map's v in mode 2, takes the constants the golden2 README names; its form is
// fitted to golden2 `selfshadow-0.png` and `selfshadow-30.png` (the penumbra ramps).
// The shadow map at a texel, clamped to its edge.
fn map_depth(texel: vec2<i32>) -> f32 {
    let n = i32(scene.self_shadow.w) - 1;
    return textureLoad(shadow_map, clamp(texel, vec2<i32>(0), vec2<i32>(n)), 0);
}

fn lit_fraction(world: vec3<f32>) -> f32 {
    if scene.self_shadow.x == 0.0 || mat.params.z == 0.0 {
        return 1.0;
    }
    let c = scene.light_view_proj * vec4<f32>(world, 1.0);
    if c.w <= 0.0 {
        return 1.0;
    }
    let p = c.xyz / c.w;
    let uv = vec2<f32>(1.0 + p.x, 1.0 - p.y) * 0.5;
    if any(clamp(uv, vec2<f32>(0.0), vec2<f32>(1.0)) != uv) {
        return 1.0;
    }
    let t = uv * scene.self_shadow.w - 0.5;
    let f = fract(t);
    let i = vec2<i32>(floor(t));
    let depth = mix(
        mix(map_depth(i), map_depth(i + vec2<i32>(1, 0)), f.x),
        mix(map_depth(i + vec2<i32>(0, 1)), map_depth(i + vec2<i32>(1, 1)), f.x),
        f.y,
    );
    var k = scene.self_shadow.y;
    if scene.self_shadow.z == 1.0 {
        k = k * uv.y;
    }
    return 1.0 - clamp(max(p.z - depth, 0.0) * k - 0.3, 0.0, 1.0);
}

// A varying at the pixel center, as `center_uv` takes the texture coordinate there.
fn center_value(v: vec3<f32>, q: f32) -> vec3<f32> {
    let o = scene.ground_shadow_plane.yz;
    let n = v * q;
    let numerator = n - dpdx(n) * o.x - dpdy(n) * o.y;
    let denominator = q - dpdx(q) * o.x - dpdy(q) * o.y;
    return numerator / denominator;
}

// The scene point at the pixel center, as `center_uv` takes the texture coordinate there.
fn center_world(world: vec3<f32>, q: f32) -> vec3<f32> {
    let o = scene.ground_shadow_plane.yz;
    let n = world * q;
    let numerator = n - dpdx(n) * o.x - dpdy(n) * o.y;
    let denominator = q - dpdx(q) * o.x - dpdy(q) * o.y;
    return numerator / denominator;
}

@fragment
fn fs_main(i: VsOut) -> @location(0) vec4<f32> {
    let lit = lit_fraction(center_world(i.world, i.clip.w));
    // Without self-shadow (toon 1) the normal is used as interpolated, not renormalized.
    var n = i.normal;
    if scene.light_dir.w != 1.0 {
        n = normalize(n);
    }
    let uv = center_uv(i.uv, i.clip.w);
    let to_light = -normalize(scene.light_dir.xyz);
    let lc = scene.light_color.rgb;
    var color = clamp(mat.ambient.rgb + mat.diffuse.rgb * lc, vec3<f32>(0.0), vec3<f32>(1.0));
    // The texture, sphere and toon tints of the material morphs do not reach the picture (golden2
    // `skin-*.png`: `matmul` and `matadd` change no texture color).
    if mat.params.x == 1.0 {
        color = color * textureSample(tex, samp, uv).rgb;
    }

    let view_n = (scene.view * vec4<f32>(normalize(n), 0.0)).xy;
    let sphere_uv = vec2<f32>(view_n.x * 0.5 + 0.5, 0.5 - view_n.y * 0.5);
    let s = textureSampleLevel(sphere, clamped, sphere_uv, 0.0).rgb;
    if mat.params.y == 1.0 {
        color = color * s;
    } else if mat.params.y == 2.0 {
        color = color + s;
    }

    var specular = vec3<f32>(0.0);
    let power = mat.specular.w;
    // Self-shadow off draws the fixed-function highlight, lit per vertex; self-shadow on lights it
    // per pixel.
    if scene.light_dir.w == 1.0 {
        specular = center_value(i.specular, i.clip.w);
    } else if power > 0.0 {
        let to_eye = normalize(scene.eye.xyz - i.world);
        let h = normalize(to_light + to_eye);
        specular = mat.specular.rgb * lc * pow(max(dot(n, h), 0.0), power);
    }
    // The toon texture has the lit end at v = 0 and the shadow color at v = 1. Under self-shadow
    // the color blends from the lit color toward the shadow color as 3 N.L, with the normal as
    // interpolated, falls from 1 to 0, or as the self-shadow falls, whichever is darker. The
    // highlight is part of the lit color only. Fitted to golden2 `selfshadow-*.png` (the ramps and
    // the flat shadowed fronts of the models), and the golden scene, frames 300 and 599.
    let ndl = dot(n, to_light);
    if scene.light_dir.w == 2.0 {
        let shade = textureSampleLevel(toon, clamped, vec2<f32>(0.5, 1.0), 0.0).rgb;
        let toon_lit = clamp(3.0 * dot(i.normal, to_light), 0.0, 1.0);
        color = mix(color * shade, color + specular, min(toon_lit, lit));
    } else {
        if scene.light_dir.w == 1.0 {
            color = color * textureSampleLevel(toon, clamped, vec2<f32>(0.5, 0.5 - 0.5 * ndl), 0.0).rgb;
        }
        color = color + specular;
    }
    return vec4<f32>(clamp(color, vec3<f32>(0.0), vec3<f32>(1.0)), mat.diffuse.a);
}

// Accessories: Direct3D 9's fixed-function lighting, `emissive + ambient * La + diffuse * Ld * N.L`
// with the normal transformed and renormalized, times the texture, and no specular. La and Ld are
// fitted to golden2 `accessory-0.png` and `accessory-30.png` (light color 0.625 in both): the
// cube faces that turn from the light give La = 0.52 * light, and the floor (N.L = 0.8165) then
// gives Ld = 16 * light, which is 10 at that light color (the README's "ten times as bright").
// Whether they follow the light color is a guess.
//
// Under self-shadow an accessory that receives it (params.z) is lit by the effect instead: the
// emissive part (scaled by the projected-shadow ambient, `params.w`) plus `ambient * La`, and the
// diffuse part `diffuse * La * N.L`, which the shadow takes away. Fitted to golden2
// `selfshadow-0.png` and `selfshadow-30.png` (shadow_floor.x: 97 lit, 92 in shadow); other
// emissive and diffuse values are extrapolated.
@fragment
fn fs_accessory(i: VsOut) -> @location(0) vec4<f32> {
    let lit = lit_fraction(center_world(i.world, i.clip.w));
    let n = normalize(i.normal);
    let uv = center_uv(i.uv, i.clip.w);
    let to_light = -normalize(scene.light_dir.xyz);
    let lc = scene.light_color.rgb;
    let ndl = max(dot(n, to_light), 0.0);
    var color = mat.emissive.rgb + mat.ambient.rgb * 0.52 * lc + mat.diffuse.rgb * 16.0 * lc * ndl;
    if mat.params.z == 1.0 && scene.self_shadow.x == 1.0 {
        color = mat.emissive.rgb * mat.params.w + (mat.ambient.rgb + mat.diffuse.rgb * ndl * lit)
            * 0.52 * lc;
    }
    color = clamp(color, vec3<f32>(0.0), vec3<f32>(1.0));
    if mat.params.x == 1.0 {
        color = color * textureSample(tex, samp, uv).rgb;
    }
    let view_n = (scene.view * vec4<f32>(n, 0.0)).xy;
    let sphere_uv = vec2<f32>(view_n.x * 0.5 + 0.5, 0.5 - view_n.y * 0.5);
    let s = textureSampleLevel(sphere, clamped, sphere_uv, 0.0).rgb;
    if mat.params.y == 1.0 {
        color = color * s;
    } else if mat.params.y == 2.0 {
        color = color + s;
    }
    return vec4<f32>(clamp(color, vec3<f32>(0.0), vec3<f32>(1.0)), mat.diffuse.a);
}

// The background picture: a quad in output pixels (`mat.diffuse` is left, top, right, bottom),
// textured with the picture.
struct PictureOut {
    @builtin(position) clip: vec4<f32>,
    @location(0) uv: vec2<f32>,
}

@vertex
fn vs_picture(@builtin(vertex_index) k: u32) -> PictureOut {
    // Two triangles: corners 0 1 2 and 2 1 3, bit 0 right, bit 1 down.
    let c = array<u32, 6>(0u, 1u, 2u, 2u, 1u, 3u)[k];
    let corner = vec2<f32>(f32(c & 1u), f32((c >> 1u) & 1u));
    let r = mat.diffuse;
    let p = mix(r.xy, r.zw, corner);
    var o: PictureOut;
    o.clip = shifted(vec4<f32>(2.0 * p.x / scene.screen.x - 1.0, 1.0 - 2.0 * p.y / scene.screen.y, 0.0, 1.0));
    o.uv = corner;
    return o;
}

// The picture is filtered anisotropically: the pixel's footprint in texels is split along its long
// axis into ceil(long / short) trilinear samples spread over the pixel, at LOD
// log2(long / samples) + 0.38. Fitted to golden2 `background-0.png` (the 1024 x 1024 texture
// drawn 286.6 x 161.7 pixels: two samples along v). A CPU model of the sampling puts a single
// trilinear sample, at any LOD, below 0.986 within 4 on the picture's pixels.
@fragment
fn fs_picture(i: PictureOut) -> @location(0) vec4<f32> {
    let uv = center_uv(i.uv, i.clip.w);
    let size = vec2<f32>(textureDimensions(tex));
    let dx = dpdx(i.uv);
    let dy = dpdy(i.uv);
    let lx = length(dx * size);
    let ly = length(dy * size);
    var axis = dx;
    var long = lx;
    var short = ly;
    if ly > lx {
        axis = dy;
        long = ly;
        short = lx;
    }
    let n = clamp(ceil(long / max(short, 1e-6)), 1.0, 16.0);
    let lod = log2(long / n) + 0.38;
    var color = vec3<f32>(0.0);
    for (var k = 0.0; k < n; k += 1.0) {
        color += textureSampleLevel(tex, samp, uv + axis * ((k + 0.5) / n - 0.5), lod).rgb;
    }
    return vec4<f32>(color / n, 1.0);
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

// The self-shadow map: depth seen from the light. Direct3D 9 puts texel centers on integer
// coordinates, so the map is shifted half a texel right and down, as `PIXEL_OFFSET_D3D9` shifts
// the picture.
@vertex
fn vs_shadow(v: VsIn) -> @builtin(position) vec4<f32> {
    let c = scene.light_view_proj * vec4<f32>(v.position, 1.0);
    let shift = 1.0 / scene.self_shadow.w;
    return vec4<f32>(c.x + shift * c.w, c.y - shift * c.w, c.z, c.w);
}

// Ground shadow: the model flattened onto y = 0 along the light, then lifted to the plane height,
// in one color (the plane matrix of the `ground` probe line).
fn ground_shadow_clip(position: vec3<f32>) -> vec4<f32> {
    let d = normalize(scene.light_dir.xyz);
    var p = position - d * (position.y / d.y);
    p.y = scene.ground_shadow_plane.x;
    return shifted(scene.view_proj * vec4<f32>(p, 1.0));
}

// The ground shadow is the edge hull's (winprobe2: no body is drawn under the ground matrix).
@vertex
fn vs_ground_shadow_edge(v: EdgeIn) -> @builtin(position) vec4<f32> {
    return ground_shadow_clip(v.position);
}

@fragment
fn fs_ground_shadow() -> @location(0) vec4<f32> {
    return scene.ground_shadow;
}

// The ground grid and the axes: each segment from `a` to `b` is a quad one pixel wide across the
// line, as Direct3D 9 rasterizes a line under multisampling (golden2 `perspective-0.png`: the
// eight samples of a column across a horizontal grid line fall on exactly one row each).
struct LineIn {
    @location(0) a: vec3<f32>,
    @location(1) b: vec3<f32>,
    @location(2) color: vec4<f32>,
    // x: 0 at `a`, 1 at `b`; y: -1 or 1, the side of the line.
    @location(3) corner: vec2<f32>,
}

@vertex
fn vs_line(v: LineIn) -> EdgeOut {
    var o: EdgeOut;
    o.color = v.color;
    var a = scene.view_proj * vec4<f32>(v.a, 1.0);
    var b = scene.view_proj * vec4<f32>(v.b, 1.0);
    if a.z < 0.0 && b.z < 0.0 {
        o.clip = vec4<f32>(0.0, 0.0, -1.0, 1.0);
        return o;
    }
    // Cut at the near plane, so a line that passes the camera keeps its part in front.
    if a.z < 0.0 {
        a = mix(a, b, a.z / (a.z - b.z));
    } else if b.z < 0.0 {
        b = mix(b, a, b.z / (b.z - a.z));
    }
    let half = scene.screen.xy * 0.5;
    var d = b.xy / b.w * half - a.xy / a.w * half;
    if dot(d, d) == 0.0 {
        d = vec2<f32>(1.0, 0.0);
    }
    d = normalize(d);
    var p = a;
    if v.corner.x == 1.0 {
        p = b;
    }
    let across = vec2<f32>(-d.y, d.x) * (0.5 * v.corner.y) / half;
    o.clip = shifted(vec4<f32>(p.xy + across * p.w, p.z, p.w));
    return o;
}

// The self-shadow map display: a quad in output pixels (`scene.display`), the map's depth in gray.
@vertex
fn vs_display(@builtin(vertex_index) k: u32) -> PictureOut {
    let c = array<u32, 6>(0u, 1u, 2u, 2u, 1u, 3u)[k];
    let corner = vec2<f32>(f32(c & 1u), f32((c >> 1u) & 1u));
    let r = scene.display;
    let p = mix(r.xy, r.zw, corner);
    var o: PictureOut;
    o.clip = shifted(vec4<f32>(2.0 * p.x / scene.screen.x - 1.0, 1.0 - 2.0 * p.y / scene.screen.y, 0.0, 1.0));
    o.uv = corner;
    return o;
}

@fragment
fn fs_display(i: PictureOut) -> @location(0) vec4<f32> {
    let n = i32(scene.self_shadow.w);
    let texel = clamp(vec2<i32>(i.uv * scene.self_shadow.w), vec2<i32>(0), vec2<i32>(n - 1));
    let depth = textureLoad(shadow_map, texel, 0);
    return vec4<f32>(depth, depth, depth, 1.0);
}
