"""Advertencias informativas; nunca sustituyen las validaciones de precios."""


def advertencias_precios(costo, menudeo, mayoreo):
    avisos = []
    if costo is not None and costo > 0:
        if menudeo is not None and menudeo > 0 and menudeo < costo:
            avisos.append({
                "campo": "precio_menudeo",
                "mensaje": (
                    "Aviso opcional: el precio de venta es inferior al costo. "
                    "Puedes guardar el artículo si ese precio es correcto."
                ),
            })
        if mayoreo is not None and mayoreo > 0 and mayoreo < costo:
            avisos.append({
                "campo": "precio_mayoreo",
                "mensaje": (
                    "Aviso opcional: el precio de mayoreo es inferior al costo. "
                    "Puedes guardar el artículo si ese precio es correcto."
                ),
            })
    return avisos
