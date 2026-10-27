            if std::thread::current().name() == Some("selfshadow_30") {
                let ordinal = stage.accessories.iter().position(|v| std::ptr::eq(v, a)).expect("accessory ordinal");
                eprintln!("FG_UPLOAD {} {}", ordinal, bytes(&body).iter().map(|b| format!("{b:02x}")).collect::<String>());
                eprintln!("FG_WORLD {} {}", ordinal, a.world.iter().map(|v| v.to_bits().to_string()).collect::<Vec<_>>().join(" "));
                let acc = &a.mesh.accessory;
                eprintln!("FG_LOCAL {} {} {} {}", ordinal, acc.vertices.len(), acc.indices.len(), acc.materials.len());
                for (i,v) in acc.vertices.iter().enumerate() {
                    eprintln!("FG_V {} {} {}", ordinal,i,v.position.iter().chain(&v.normal).chain(&v.texcoord).map(|v| v.to_bits().to_string()).collect::<Vec<_>>().join(" "));
                }
                eprintln!("FG_I {} {}", ordinal,acc.indices.iter().map(|v|v.to_string()).collect::<Vec<_>>().join(" "));
                eprintln!("FG_A {} {}", ordinal,acc.face_material.iter().map(|v|v.to_string()).collect::<Vec<_>>().join(" "));
                for t in &acc.attribute_table { eprintln!("FG_T {} {} {} {} {} {}",ordinal,t.id,t.face_start,t.face_count,t.vertex_start,t.vertex_count); }
                for (i,m) in acc.materials.iter().enumerate() {
                    eprintln!("FG_M {} {} {}",ordinal,i,m.diffuse.iter().chain(&m.ambient).chain(&m.specular).chain(&m.emissive).chain(std::iter::once(&m.power)).map(|v|v.to_bits().to_string()).collect::<Vec<_>>().join(" "));
                }
            }
