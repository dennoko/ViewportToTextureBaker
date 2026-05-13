# Viewport to Texture Baker — 使い方ガイド

## 概要

選択した複数のメッシュオブジェクトのマテリアル「ビューポート表示」設定（Base Color・Metallic・Roughness）を読み取り、UV マップを使って 1 枚のテクスチャへ合成・出力する拡張機能です。

---

## Blender へのインストール手順

### 方法 A — ZIP ファイルとしてインストール（推奨）

1. 拡張機能のフォルダ全体（`ViewportToTextureBaker/`）を ZIP ファイルに圧縮します。  
   - Windows なら: フォルダを右クリック →「圧縮」→「ZIP ファイル」
2. Blender を起動し、メニューから **Edit → Preferences** を開きます。
3. 左ペインで **Extensions** タブを選択します。
4. 右上のドロップダウン（`∨`）をクリックし、**Install from Disk...** を選びます。
5. 作成した ZIP ファイルを選択して **Install** をクリックします。
6. 拡張機能の一覧に **Viewport to Texture Baker** が表示されるので、チェックをオンにして有効化します。

> **Tip:** Blender 4.2 以降では ZIP をそのまま Blender ウィンドウにドラッグ＆ドロップしてもインストールできます。

---

### 方法 B — 開発用リポジトリとして追加（開発者向け）

1. Blender の **Edit → Preferences → Extensions** を開きます。
2. **Repositories** セクションの `+` ボタンをクリックし **Add Local Repository** を選択します。
3. `Source Directory` に `ViewportToTextureBaker/` フォルダの **親ディレクトリ**（例: `C:\Users\YourName\Programming\Blender_Extension\`）を指定します。
4. **Save Preferences** を押すと拡張機能がリストに現れるので、チェックをオンにします。

このアドレスでは ZIP 化なしに直接フォルダを編集できます。

---

## 前提条件

| 条件 | 詳細 |
|------|------|
| Blender バージョン | 4.2.0 以降（5.x 対応） |
| UV マップ | 対象オブジェクトの UV が展開済みで、アイランドが **重なっていない** こと |
| マテリアル | 各マテリアルにビューポート表示用の Color / Metallic / Roughness 値が設定されていること |
| オブジェクトモード | 3D ビューポートが **Object Mode** であること |

---

## 使い方

### 基本操作

1. 3D ビューポートで、テクスチャ出力したいメッシュオブジェクトを **1 つ以上選択** します。  
   （複数選択の場合、Shift+クリック または A キーで全選択）

2. 右クリックして **オブジェクトコンテキストメニュー** を開きます。

3. メニュー下部の **「Export Viewport to Textures」** をクリックします。

4. ベイクが自動的に実行され、完了するとステータスバーに保存先パスが表示されます。

---

### 実行前の設定ダイアログ

| 設定項目 | 内容 | デフォルト |
|---------|------|-----------|
| **Resolution** | 出力テクスチャの解像度（512 / 1024 / 2048 / 4096） | 2048 |
| **Margin (px)** | UV アイランド境界の塗り足し幅（ブリード） | 16 px |
| **Output Path** | テクスチャの保存先フォルダ | `Documents/ViewportToTextureBaker/<ファイル名>/` |
| **Overwrite Existing** | 同名ファイルを上書きするか。OFF の場合は `_0001`, `_0002`... の連番で保存 | ON |
| **Pack Metallic/Roughness** | Metallic と Roughness を 1 枚にまとめる | OFF |
| **Metallic →**（Pack ON 時） | パック画像の Metallic を格納するチャンネル | B |
| **Roughness →**（Pack ON 時） | パック画像の Roughness を格納するチャンネル | G |

右クリックメニューから実行すると、まずこの設定ダイアログが表示されます。  
設定を確定してからベイクと保存が開始されるため、保存後に不要な再設定が発生しません。

---

## 出力ファイル

### Pack OFF（個別ファイル）

```
<OutputPath>/
├── <BlendFileName>_BaseColor.png      ← RGB: ビューポート Base Color
├── <BlendFileName>_Metallic.png       ← グレースケール: ビューポート Metallic 値
└── <BlendFileName>_Roughness.png      ← グレースケール: ビューポート Roughness 値
```

### Pack ON（メタリック/ラフネス結合）

```
<OutputPath>/
├── <BlendFileName>_BaseColor.png          ← RGB: Base Color（変わらず）
└── <BlendFileName>_MetallicRoughness.png  ← 指定チャンネルに Metallic + Roughness を格納
```

例: デフォルト設定（Metallic → B、Roughness → G）なら ORM テクスチャに近い形式になります。

---

## 内部動作の概要

1. レンダリングエンジンを一時的に **Cycles** へ切り替えます。
2. 各マテリアルに **Emission ノード**（ビューポート値を出力）と **Image Texture ノード**（ベイク先）を一時的に追加します。
3. `Emit` タイプで Cycles ベイクを 3 回実行（BaseColor / Metallic / Roughness）。
4. ベイク後、一時ノードを削除してマテリアルを元の状態に復元し、レンダリングエンジンも元に戻します。

---

## よくある質問

**Q. ベイクに時間がかかる**  
A. Cycles ベイクのため、解像度が高いほど時間がかかります。作業初期は 1024 で確認し、最終出力時に 2048 / 4096 に変更することをお勧めします。

**Q. 「These objects have no UV map」と表示される**  
A. 選択オブジェクトに UV マップが存在しません。UV Editor で UV 展開を行ってから再実行してください。

**Q. テクスチャが全部黒い**  
A. マテリアルのビューポート表示の Base Color が黒（0, 0, 0）になっていないか確認してください。Shader Editor 側の Principled BSDF の色ではなく、**プロパティパネル → マテリアル → ビューポート表示** の設定が参照されます。

**Q. 複数オブジェクトを選択したのに 1 つだけしか出力されない**  
A. UV アイランドがオブジェクト間で重なっていると正しく出力されません。UV Editor で全オブジェクトの UV を重ならないようにレイアウトしてから再実行してください。

**Q. Cycles がない / エラーになる**  
A. Blender に Cycles Render Engine が含まれている必要があります（標準インストールに含まれています）。カスタムビルドの場合は Cycles を有効化してください。

---

## アンインストール

1. **Edit → Preferences → Extensions** を開きます。
2. **Viewport to Texture Baker** を見つけ、チェックをオフにして無効化します。
3. 右クリック →「Remove」で完全に削除できます。
