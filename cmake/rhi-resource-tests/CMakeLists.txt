cmake_minimum_required(VERSION 3.16)
project(MikuDanceStudioResourceTests LANGUAGES CXX)
include(CTest)
get_filename_component(MDS_SOURCE "${CMAKE_CURRENT_LIST_DIR}/../.." ABSOLUTE)
add_library(mds_rhi_resources
    "${MDS_SOURCE}/src/render/rhi_null.cpp"
    "${MDS_SOURCE}/src/render/rhi_image.cpp"
    "${MDS_SOURCE}/src/render/rhi_assets.cpp"
    "${MDS_SOURCE}/src/render/rhi_material_textures.cpp"
    "${MDS_SOURCE}/src/render/rhi_shader_inputs.cpp")
target_compile_features(mds_rhi_resources PUBLIC cxx_std_17)
target_include_directories(mds_rhi_resources PUBLIC "${MDS_SOURCE}/include"
    PRIVATE "${MDS_SOURCE}/third_party/stb")
foreach(test IN ITEMS null image assets material_textures texture_preparation history)
    add_executable(rhi_${test}_test "${MDS_SOURCE}/tests/rhi_${test}_test.cpp")
    target_link_libraries(rhi_${test}_test PRIVATE mds_rhi_resources)
endforeach()
add_test(NAME rhi_null COMMAND rhi_null_test)
add_test(NAME rhi_image COMMAND rhi_image_test "${MDS_SOURCE}/res/assets/hud_sprites.png")
add_test(NAME rhi_assets COMMAND rhi_assets_test "${MDS_SOURCE}/res/assets")
add_test(NAME rhi_material_textures COMMAND rhi_material_textures_test)
add_test(NAME rhi_texture_preparation COMMAND rhi_texture_preparation_test)
add_test(NAME rhi_history COMMAND rhi_history_test)
