#pragma once
#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <vector>
namespace model_reader_fixture {
struct Bytes {
    std::vector<std::uint8_t> data;
    std::size_t position = 0;
    void byte(std::uint8_t value) { data.push_back(value); }
    void word(std::uint16_t value) {
        byte(static_cast<std::uint8_t>(value));
        byte(static_cast<std::uint8_t>(value >> 8));
    }
    void dword(std::uint32_t value) {
        word(static_cast<std::uint16_t>(value));
        word(static_cast<std::uint16_t>(value >> 16));
    }
    void number(float value) {
        std::uint32_t bits = 0;
        std::memcpy(&bits, &value, sizeof bits);
        dword(bits);
    }
    void floats(std::size_t count, float value = 0) {
        for (std::size_t index = 0; index < count; ++index) number(value);
    }
    void zeros(std::size_t count) { data.insert(data.end(), count, 0); }
    void text(char value = 0) {
        if (!value) { dword(0); return; }
        dword(2); byte(static_cast<std::uint8_t>(value)); byte(0);
    }
    static int read(void* opaque, void* output, std::size_t size) {
        auto& bytes = *static_cast<Bytes*>(opaque);
        const auto available = bytes.data.size() - bytes.position;
        const auto actual = std::min(available, size);
        if (actual) std::memcpy(output, bytes.data.data() + bytes.position, actual);
        bytes.position += actual;
        return static_cast<int>(actual);
    }
};
inline Bytes Pmd(bool english = true, bool physics = true) {
    Bytes bytes;
    bytes.byte('P'); bytes.byte('m'); bytes.byte('d');
    bytes.number(1.0f);
    bytes.zeros(20); bytes.data[7] = 'P';
    bytes.zeros(256);
    bytes.dword(1);
    bytes.floats(3, 1); bytes.floats(3); bytes.floats(2);
    bytes.word(0); bytes.word(0); bytes.byte(100); bytes.byte(0);
    bytes.dword(3); bytes.word(0); bytes.word(0); bytes.word(0);
    bytes.dword(1);
    bytes.floats(4, 1); bytes.number(4); bytes.floats(3); bytes.floats(3);
    bytes.byte(2); bytes.byte(1); bytes.dword(3);
    const auto texture = bytes.data.size(); bytes.zeros(20); bytes.data[texture] = 't';
    bytes.word(1);
    const auto bone = bytes.data.size(); bytes.zeros(20); bytes.data[bone] = 'B';
    bytes.word(0xffff); bytes.word(0); bytes.byte(0); bytes.word(0);
    bytes.floats(3, 2);
    bytes.word(1); bytes.word(0); bytes.word(0); bytes.byte(1);
    bytes.word(4); bytes.number(0.25f); bytes.word(0);
    bytes.word(1);
    const auto morph = bytes.data.size(); bytes.zeros(20); bytes.data[morph] = 'M';
    bytes.dword(1); bytes.byte(0); bytes.dword(0); bytes.floats(3, 3);
    bytes.byte(1); bytes.word(0);
    bytes.byte(1); bytes.zeros(50);
    bytes.dword(1); bytes.word(0); bytes.byte(0);
    bytes.byte(english ? 1 : 0);
    if (english) {
        const auto name = bytes.data.size(); bytes.zeros(20); bytes.data[name] = 'E';
        bytes.zeros(256);
        bytes.zeros(20);
        bytes.zeros(50);
    }
    for (int index = 0; index < 10; ++index) {
        const auto toon = bytes.data.size(); bytes.zeros(100);
        bytes.data[toon] = 'T';
    }
    if (physics) {
        bytes.dword(1);
        const auto rigid = bytes.data.size(); bytes.zeros(20);
        bytes.data[rigid] = 'R';
        bytes.word(0); bytes.byte(1); bytes.word(0); bytes.byte(0);
        bytes.floats(3, 1); bytes.floats(3); bytes.floats(3);
        bytes.floats(5); bytes.byte(0);
        bytes.dword(1);
        const auto joint = bytes.data.size(); bytes.zeros(20);
        bytes.data[joint] = 'J';
        bytes.dword(0); bytes.dword(0);
        bytes.floats(6); bytes.floats(12); bytes.floats(6);
    }
    return bytes;
}
inline Bytes Pmx(bool physics = false) {
    Bytes bytes;
    bytes.byte('P'); bytes.byte('M'); bytes.byte('X'); bytes.byte(' ');
    bytes.number(2.0f);
    bytes.byte(8);
    for (auto setting : {0, 0, 2, 1, 1, 1, 1, 1}) bytes.byte(setting);
    bytes.text('P'); bytes.text(); bytes.text(); bytes.text();
    bytes.dword(1);
    bytes.floats(3, 1); bytes.floats(3); bytes.floats(2);
    bytes.byte(0); bytes.byte(0); bytes.number(1);
    bytes.dword(3); bytes.word(0); bytes.word(0); bytes.word(0);
    bytes.dword(1); bytes.text('t');
    bytes.dword(1); bytes.text('M'); bytes.text();
    bytes.floats(4, 1); bytes.floats(3); bytes.number(4);
    bytes.floats(3); bytes.byte(0x10); bytes.floats(4);
    bytes.number(1); bytes.byte(0xff); bytes.byte(0xff);
    bytes.byte(0); bytes.byte(1); bytes.byte(0);
    bytes.text('N'); bytes.dword(3);
    bytes.dword(1); bytes.text('B'); bytes.text();
    bytes.floats(3, 2); bytes.byte(0xff); bytes.dword(0);
    bytes.word(0x0009); bytes.byte(0);
    bytes.dword(1); bytes.text('X'); bytes.text();
    bytes.byte(4); bytes.byte(1); bytes.dword(1);
    bytes.word(0); bytes.floats(3, 3);
    bytes.dword(2);
    bytes.text('R'); bytes.text(); bytes.byte(1); bytes.dword(1);
    bytes.byte(0); bytes.byte(0);
    bytes.text('D'); bytes.text(); bytes.byte(0); bytes.dword(0);
    bytes.dword(physics ? 1 : 0);
    if (physics) {
        bytes.text('Q'); bytes.text();
        bytes.byte(0); bytes.byte(1); bytes.word(0); bytes.byte(0);
        bytes.floats(3, 1); bytes.floats(3); bytes.floats(3);
        bytes.floats(5); bytes.byte(0);
        bytes.dword(1);
        bytes.text('J'); bytes.text(); bytes.byte(0);
        bytes.byte(0); bytes.byte(0);
        bytes.floats(6); bytes.floats(12); bytes.floats(6);
    }
    return bytes;
}
}
