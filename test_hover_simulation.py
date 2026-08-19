"""
Simulação de hover: mede o tempo de OCR num RECORTE pequeno,
com o modelo já carregado — é isso que representa o uso real
(app já aberto, usuário passando o mouse em cima de texto).

Uso:
    python test_hover_simulation.py caminho\imagem.png
    python test_hover_simulation.py caminho\imagem.png x1 y1 x2 y2

Se não passar as coordenadas do recorte, ele usa por padrão
o terço inferior da imagem (onde legendas costumam ficar) e
salva o recorte como "recorte_teste.png" pra você conferir
se pegou a região certa.
"""

import sys
import time
from PIL import Image


def main():
    if len(sys.argv) < 2:
        print("Uso: python test_hover_simulation.py caminho\\imagem.png [x1 y1 x2 y2]")
        sys.exit(1)

    caminho_imagem = sys.argv[1]
    img = Image.open(caminho_imagem)
    largura, altura = img.size
    print(f"Imagem original: {largura}x{altura}")

    if len(sys.argv) >= 6:
        x1, y1, x2, y2 = map(int, sys.argv[2:6])
    else:
        # padrão: terço inferior, faixa central — tipo onde fica legenda
        x1 = int(largura * 0.05)
        y1 = int(altura * 0.85)
        x2 = int(largura * 0.55)
        y2 = int(altura * 0.95)

    recorte = img.crop((x1, y1, x2, y2))
    recorte.save("recorte_teste.png")
    print(f"Recorte: {x2 - x1}x{y2 - y1} pixels (salvo em recorte_teste.png — confere se pegou o texto certo)")

    print("\nCarregando modelo (isso só acontece 1x, na abertura do app)...")
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
    print(f"Tempo de carregamento do modelo: {time.time() - inicio_load:.2f}s (não se repete)")

    print("\nSimulando 3 'hovers' seguidos no mesmo recorte (modelo já quente):")
    import numpy as np
    recorte_np = np.array(recorte.convert("RGB"))

    for i in range(1, 4):
        inicio_hover = time.time()
        resultados = ocr.predict(recorte_np)
        tempo_hover = time.time() - inicio_hover

        textos = []
        for res in resultados:
            textos.extend(res.get("rec_texts", []))

        print(f"  Hover {i}: {tempo_hover:.3f}s — texto: {textos}")


if __name__ == "__main__":
    main()