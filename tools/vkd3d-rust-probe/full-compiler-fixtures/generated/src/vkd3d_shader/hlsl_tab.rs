/* Bison implementation for Yacc-like parsers in C

   Copyright (C) 1984, 1989-1990, 2000-2015, 2018-2021 Free Software Foundation,
   Inc.

   This program is free software: you can redistribute it and/or modify
   it under the terms of the GNU General Public License as published by
   the Free Software Foundation, either version 3 of the License, or
   (at your option) any later version.

   This program is distributed in the hope that it will be useful,
   but WITHOUT ANY WARRANTY; without even the implied warranty of
   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
   GNU General Public License for more details.

   You should have received a copy of the GNU General Public License
   along with this program.  If not, see <https://www.gnu.org/licenses/>.  */
/* As a special exception, you may create a larger work that contains
   part or all of the Bison parser skeleton and distribute that work
   under terms of your choice, so long as that work isn't itself a
   parser generator using the skeleton or a modified version thereof
   as a parser skeleton.  Alternatively, if you modify or redistribute
   the parser skeleton itself, you may (at your option) remove this
   special exception, which will cause the skeleton and the resulting
   Bison output files to be licensed under the GNU General Public
   License without this special exception.

   This special exception was added by the Free Software Foundation in
   version 2.2 of Bison.  */
pub type size_t = usize;
#[repr(C)]
pub struct list {
    pub next: *mut list,
    pub prev: *mut list,
}
#[repr(C)]
pub struct hlsl_block {
    pub instrs: list,
    pub value: *mut hlsl_ir_node,
}
#[repr(C)]
pub struct hlsl_src {
    pub node: *mut hlsl_ir_node,
    pub entry: list,
}
#[repr(C)]
pub struct hlsl_attribute {
    pub name: *const ::core::ffi::c_char,
    pub instrs: hlsl_block,
    pub loc: vkd3d_shader_location,
    pub args_count: ::core::ffi::c_uint,
    pub args: [hlsl_src; 0],
}
#[repr(C)]
pub struct vkd3d_shader_location {
    pub source_name: *const ::core::ffi::c_char,
    pub line: ::core::ffi::c_uint,
    pub column: ::core::ffi::c_uint,
}
#[repr(C)]
pub struct parse_initializer {
    pub args: *mut *mut hlsl_ir_node,
    pub args_count: ::core::ffi::c_uint,
    pub instrs: *mut hlsl_block,
    pub braces: bool,
    pub loc: vkd3d_shader_location,
}
offset_of!(
                                            hlsl_attribute, args[(* yyvsp.offset(- 2isize)).initializer
                                            .args_count as usize]
                                        ) as size_t;
