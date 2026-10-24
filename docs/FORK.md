# MikuDanceStudio-J について

MikuDanceStudio-J は [jstzwj/MikuDanceStudio](https://github.com/jstzwj/MikuDanceStudio) のフォークです。
上流は MikuMikuDance v9.32 を動作レベルで移植するプロジェクトです。
このフォークは上流のコードをそのまま受け継ぎ、不具合の修正、検証ツール、Rust への移行作業を加えています。

## 上流との関係

| ブランチ | 中身 |
|---|---|
| `main` | 上流 `main` の `d7425a5`（2026-10-20、VERSION 10.04）に、このフォークの 4 コミットを足したもの |
| `next` | 上流 `next` と同じ。2026-10-25 時点でどちらも `9ef4817` |
| `rm-*` | Rust 移行の PR スタック（未マージ） |

2026-10-25 時点で、上流 `main` はフォーク点より 6 コミット進んでいます（`471159b`、VERSION 10.05）。

上流を取り込む手順は次のとおりです。

```sh
git remote add upstream https://github.com/jstzwj/MikuDanceStudio.git
git fetch upstream
git merge upstream/main
```

取り込むときは次の 2 点に注意してください。

- 上流は `docs/ALIGNMENT_WORKLOG.md` を `docs/archive/alignment_worklog_2026-09_10.md` に移しました。このフォークが追記した keyframe pool の項目は、移動先のファイルに移してください。
- 上流は `src/window/command_frame_edit.cpp`、`command_frame_register.cpp`、`src/model/add_model.cpp`、`include/mikudancestudio/model_layout.hpp` を変えています。どれも keyframe pool 検証の対象です。取り込んだら `tools/keypool_check/run.sh` を実行してください。そのうえで [verify-keyframe-pool](../.claude/skills/verify-keyframe-pool/SKILL.md) の手順に従って、同期コミットを進めます。

## このフォークで加えたもの

| 内容 | 場所 | 状態 |
|---|---|---|
| keyframe 登録が track の先頭レコードを奪う不具合と、プール末尾の範囲外読み出しの修正 | `src/model/keyframe_common.hpp`、`key_registrars.cpp`、`model_keyframe_edit.cpp` | `main`（`eb6a174`） |
| keyframe pool の有界検証 | `tools/keypool_check/`、`.claude/skills/verify-keyframe-pool/` | `main` |
| Serena、CodeGraph、Graphify の設定 | `.serena/`、`graphify-out/`、`AGENTS.md` | `main` |
| Rust 移行 wave 1 の計画と試作の記録 | [RUST_MIGRATION_PLAN.md](RUST_MIGRATION_PLAN.md)、[prototypes/](prototypes/) | [PR #1](https://github.com/geekjapan/MikuDanceStudio-J/pull/1) |
| Rust 移行 RM-1 から RM-9 | `rust/`、`tests/fixtures/rust/`、`tools/fixtures/`、`tools/oracle/`、`tools/rust/`、`tools/vkd3d/` | [PR #2](https://github.com/geekjapan/MikuDanceStudio-J/pull/2) から [PR #10](https://github.com/geekjapan/MikuDanceStudio-J/pull/10) |
| vkd3d-shader の不具合 2 件 | [#11](https://github.com/geekjapan/MikuDanceStudio-J/issues/11)、[#12](https://github.com/geekjapan/MikuDanceStudio-J/issues/12) | 上流への報告は保留 |

## ドキュメント

| 文書 | 内容 | 由来 |
|---|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | 子システムの境界と、意図して残している差異 | 上流 |
| [PORTING_STATUS.md](PORTING_STATUS.md) | 移植と検証の状態 | 上流 |
| [X64_RECONSTRUCTION.md](X64_RECONSTRUCTION.md) | 参照バイナリと証拠の扱い | 上流 |
| [ALIGNMENT_WORKLOG.md](ALIGNMENT_WORKLOG.md) | 対照作業の記録 | 上流、このフォークが追記 |
| [RELEASES.md](RELEASES.md) | 版番号とリリース手順 | 上流 |
| [reconstruction/](reconstruction/) | 旧 x86 の台帳 | 上流 |
| [RUST_MIGRATION_PLAN.md](RUST_MIGRATION_PLAN.md) | Rust 移行の計画 | このフォーク |
| [prototypes/](prototypes/) | Bullet と MME の試作の記録 | このフォーク |

上流の文書は主に中国語です。このフォークで足した文書は英語か日本語です。

`ALIGNMENT_WORKLOG.md` の 13 行は、文字が `???` に置き換わっています。
この 13 行は上流のコミット `29582c3`、`52d969d`、`d7425a5` で、最初から化けた状態で追加されました。元の文はどのコミットにも残っていません。
上流の移動先ファイルでは、同じ節が読める文章に書き直されています。上流を取り込めば解消します。
上流には文書の索引 `docs/README.md` も新しくできています。これも取り込みで入ります。

## 版番号とリリース

`VERSION` はフォーク点の上流の版、10.04 のままです。このフォーク独自の版番号はまだ決めていません。

`.github/workflows/release.yml` は上流から受け継いだもので、`v*` タグを push すると動きます。
このフォークは現在 GitHub Actions を使っていないので、リリース用のタグは push しません。

## ライセンス

[LICENSE](../LICENSE) は上流と同じ内容です。
受け継いだコードも、このフォークでの変更も、現在はすべてこの条項の下にあります。
このフォーク独自の部分に別のライセンスを付けるかどうかは、まだ決めていません。
決めたら、対象の範囲とあわせてここと README に書きます。
