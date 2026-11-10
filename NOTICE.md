# 第三方声明

本项目在设计和实现上参考了以下开源项目，按 MIT 许可要求在此保留其版权声明。

## ivandokov/phockup

- 仓库：https://github.com/ivandokov/phockup
- 许可：MIT License，Copyright (c) 2017 Ivan Dokov - www.dokov.bg
- 借鉴内容：
  - 硬链接整理模式（原项目的 `--link`，本项目的「链接」方式）
  - 整理后清理空目录（原项目的 `--rmdirs`，本项目的「整理后删掉变空的文件夹」）
  - 基于文件内容逐字节比对来识别重复文件（原项目用 `filecmp.cmp(shallow=False)`）

以上功能按本项目的结构重新实现，未直接复制源文件。实现上的差异：跨卷或不支持硬链接的文件系统会退回复制，原项目直接报错；空目录清理只删因本次整理而变空的目录，并保护源目录根。

## 调研过但未复制代码的项目

- jmathai/elodie — https://github.com/jmathai/elodie
- TheLastGimbus/GooglePhotosTakeoutHelper — https://github.com/TheLastGimbus/GooglePhotosTakeoutHelper

只看了功能范围与产品形态，没有使用其代码。

## 本项目

图片整理（ImageSorter）— MIT License，Copyright (c) 2026 内战狂热爱好者。
完整许可文本见 [LICENSE](LICENSE)。
