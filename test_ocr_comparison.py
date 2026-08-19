"""
Teste comparativo: PaddleOCR vs EasyOCR em texto coreano.

Objetivo: rodar os dois engines na MESMA imagem e comparar
texto reconhecido, confiança e tempo — pra decidir qual usar
como principal e qual como fallback no hallo.

Instalação:
    pip install easyocr
    pip install paddleocr paddlepaddle

Uso:
    python test_ocr_comparison.py caminho/para/sua/imagem.png

Dica: teste com prints reais do seu caso de uso — tela de jogo,
legenda de Netflix, letra de música na tela. Fonte estilizada é
onde a diferença entre os dois engines costuma aparecer de verdade.
"""

import sys
import time


def testar_easyocr(caminho_imagem):
    print("\n" + "=" * 50)
    print("EasyOCR")
    print("=" * 50)

    inicio_load = time.time()
    import easyocr
    reader = easyocr.Reader(['ko'])
    tempo_load = time.time() - inicio_load
    print(f"Tempo de inicialização: {tempo_load:.2f}s")

    inicio_scan = time.time()
    resultados = reader.readtext(caminho_imagem)
    tempo_scan = time.time() - inicio_scan
    print(f"Tempo de leitura: {tempo_scan:.2f}s")

    print(f"\n{len(resultados)} região(ões) de texto encontrada(s):")
    for bbox, texto, confianca in resultados:
        print(f"  texto: {texto!r:<30} confiança: {confianca:.2%}")


def testar_paddleocr(caminho_imagem):
    print("\n" + "=" * 50)
    print("PaddleOCR")
    print("=" * 50)

    inicio_load = time.time()
    from paddleocr import PaddleOCR
    ocr = PaddleOCR(
        enable_mkldnn=False,
        text_detection_model_name='PP-OCRv5_mobile_det',
        text_recognition_model_name='korean_PP-OCRv5_mobile_rec',
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
    )
    tempo_load = time.time() - inicio_load
    print(f"Tempo de inicialização: {tempo_load:.2f}s")

    inicio_scan = time.time()
    resultados = ocr.predict(caminho_imagem)
    tempo_scan = time.time() - inicio_scan
    print(f"Tempo de leitura: {tempo_scan:.2f}s")

    for res in resultados:
        textos = res.get("rec_texts", [])
        scores = res.get("rec_scores", [])
        print(f"\n{len(textos)} região(ões) de texto encontrada(s):")
        for texto, confianca in zip(textos, scores):
            print(f"  texto: {texto!r:<30} confiança: {confianca:.2%}")


def main():
    if len(sys.argv) < 2:
        print("Uso: python test_ocr_comparison.py caminho/para/imagem.png")
        sys.exit(1)

    caminho_imagem = sys.argv[1]

    testar_easyocr(caminho_imagem)
    testar_paddleocr(caminho_imagem)

    print("\n" + "=" * 50)
    print("Compare acima: texto reconhecido, confiança e tempo.")
    print("O que importa mais pro nosso caso: qual leu CERTO,")
    print("não só qual foi mais rápido.")
    print("=" * 50)


if __name__ == "__main__":
    main()