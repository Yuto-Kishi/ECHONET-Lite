import cv2
import pytesseract
import numpy as np

# Macの場合、Homebrewでインストールしていればパス指定は基本的に不要です。
# もしエラーが出る場合は、ターミナルで `which tesseract` を打ち、そのパスを以下に設定してください。
# pytesseract.pytesseract.tesseract_cmd = '/opt/homebrew/bin/tesseract'


def preprocess_image(img):
    """
    OCRの精度を上げるための画像加工
    """
    # 1. グレースケール化
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # 2. 2値化（白と黒だけにする）
    # 部屋の明るさに合わせて '80' の数値を調整してください (0〜255)
    # 数字が黒で背景がグレーなら THRESH_BINARY
    # 数字が白(液晶が光っている)なら THRESH_BINARY_INV などを試します
    _, binary = cv2.threshold(gray, 80, 255, cv2.THRESH_BINARY_INV)

    # ノイズ除去
    kernel = np.ones((2, 2), np.uint8)
    binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)

    return binary


def main():
    # Macの標準カメラは '0' で認識されます
    cap = cv2.VideoCapture(0)

    # カメラが開けない場合のチェック
    if not cap.isOpened():
        print("エラー: カメラを開けませんでした。")
        print("「システム設定」→「プライバシーとセキュリティ」→「カメラ」で、")
        print("使用しているターミナルやエディタ(VSCodeなど)に許可を与えてください。")
        return

    print("開始します。終了するには映像ウィンドウを選択して 'q' を押してください。")

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        # --- 重要: 読み取り範囲の指定（ROI） ---
        # 画面中央を切り抜きます。カメラの位置に合わせて数値を調整してください。
        h, w, _ = frame.shape
        # 上下左右の余白をカットして中央を見る設定
        crop_img = frame[int(h / 3) : int(h * 2 / 3), int(w / 3) : int(w * 2 / 3)]

        # 画像加工
        processed = preprocess_image(crop_img)

        # --- OCR実行 ---
        # --psm 7: 1行のテキストとして扱う
        # outputbase digits: 数字のみを優先
        config = "--psm 7 -c tessedit_char_whitelist=0123456789."
        try:
            text = pytesseract.image_to_string(processed, config=config)
            text = text.strip()  # 空白削除

            # 何か文字が取れたら表示
            if text:
                print(f"読み取り値: {text}")

        except pytesseract.TesseractNotFoundError:
            print(
                "エラー: Tesseractが見つかりません。brew install tesseract しましたか？"
            )
            break

        # 確認用ウィンドウ表示
        cv2.imshow("Original (Crop)", crop_img)
        cv2.imshow("Processed (Black/White)", processed)

        # 'q' キーで終了
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
