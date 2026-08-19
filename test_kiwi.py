"""
Teste rápido de lematização coreana com o Kiwi (kiwipiepy).

Instalação:
    pip install kiwipiepy

Uso:
    python test_kiwi.py
"""

from kiwipiepy import Kiwi

# Frases de teste — misturando verbo conjugado, gíria e expressão comum
# de música/drama, pra ver como o Kiwi se comporta em texto "real".
frases_teste = [
    "했어요",                    # passado polido de 하다 (fazer)
    "사랑해",                    # "amo você" — informal, comum em música
    "밥 먹었어?",                 # "você comeu?" — coloquial
    "너무 예뻐요",                 # "muito bonita" — adjetivo conjugado
    "가고 싶어요",                 # "quero ir" — verbo + desejo
    "아버지가방에들어가신다",         # frase clássica de teste de ambiguidade
    "오빠 어디야?",                # gíria comum (oppa, onde você tá)
    "진짜 대박이다",                # gíria (sério, incrível)
]


def main():
    kiwi = Kiwi()

    for frase in frases_teste:
        print(f"\n입력 (entrada): {frase}")
        resultado = kiwi.tokenize(frase)
        for token in resultado:
            # form = forma/raiz que o Kiwi identificou (o que você vai
            #        usar pra buscar no dicionário)
            # tag  = classe gramatical (VV = verbo, NNG = substantivo comum,
            #        JX = partícula, etc. — tabela completa na doc do Kiwi)
            print(
                f"  forma: {token.form:<10} "
                f"tag: {token.tag:<6} "
                f"posição: {token.start}-{token.start + token.len}"
            )


if __name__ == "__main__":
    main()