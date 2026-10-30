"""app/claves.py: los dos algoritmos de contraseña, la comparación en tiempo constante y la política."""

import hashlib
import inspect

import pytest

from app import claves

SAL = bytes(range(32))


def test_pbkdf2_usa_600000_iteraciones_en_el_codigo():
    # Los tests bajan las iteraciones (conftest.iteraciones_rapidas); el valor real debe seguir en el código.
    assert "ITERACIONES_PBKDF2 = 600_000" in inspect.getsource(claves)
    assert claves.LARGO_SAL == 32


def test_pbkdf2_vector_conocido(monkeypatch):
    # Vector de prueba de PBKDF2-HMAC-SHA256 (P="password", S="salt", c=1, 32 bytes).
    monkeypatch.setattr(claves, "ITERACIONES_PBKDF2", 1)
    esperado = bytes.fromhex("120fb6cffcf8b32c43e7225256c4f837a86548c92ccc35480805987cb70be17b")
    assert claves.calcular("PBKDF2_SHA256", "password", b"salt") == esperado


def test_sha2_512_es_sal_mas_utf16le():
    # HASHBYTES('SHA2_512', @sal + CAST(N'Ab' AS VARBINARY)): NVARCHAR se guarda en UTF-16LE.
    esperado = hashlib.sha512(SAL + b"A\x00b\x00").digest()
    assert claves.calcular("SHA2_512", "Ab", SAL) == esperado
    assert len(esperado) == 64


def test_sha2_512_de_la_contrasena_por_defecto_con_tildes():
    clave = "Contraseña#1"
    assert claves.calcular("SHA2_512", clave, SAL) == hashlib.sha512(SAL + clave.encode("utf-16-le")).digest()


@pytest.mark.parametrize("algoritmo", ["SHA2_512", "PBKDF2_SHA256"])
def test_verificar(algoritmo):
    guardado = claves.calcular(algoritmo, "Clave#Segura2026", SAL)
    assert claves.verificar(algoritmo, "Clave#Segura2026", SAL, guardado)
    assert not claves.verificar(algoritmo, "Clave#Segura2027", SAL, guardado)
    assert not claves.verificar(algoritmo, "clave#segura2026", SAL, guardado)
    assert not claves.verificar(algoritmo, "Clave#Segura2026", b"\x01" * 32, guardado)


@pytest.mark.parametrize("algoritmo, clave, sal, guardado", [
    ("MD5", "x", SAL, b"x"),
    ("SHA2_512", "", SAL, b"x"),
    ("SHA2_512", "x" * 129, SAL, b"x"),
    ("SHA2_512", "x", b"", b"x"),
    ("SHA2_512", "x", SAL, b""),
])
def test_verificar_casos_invalidos_no_verifican(algoritmo, clave, sal, guardado):
    assert claves.verificar(algoritmo, clave, sal, guardado) is False


def test_verificar_compara_en_tiempo_constante(monkeypatch):
    llamadas = []
    original = claves.hmac.compare_digest
    monkeypatch.setattr(claves.hmac, "compare_digest", lambda a, b: llamadas.append(1) or original(a, b))
    guardado = claves.calcular("SHA2_512", "x", SAL)
    claves.verificar("SHA2_512", "x", SAL, guardado)
    assert llamadas == [1]


def test_nuevo_hash_usa_pbkdf2_con_sal_aleatoria():
    h1, s1, a1 = claves.nuevo_hash("Clave#Segura2026")
    h2, s2, _ = claves.nuevo_hash("Clave#Segura2026")
    assert a1 == "PBKDF2_SHA256"
    assert len(s1) == 32 and s1 != s2 and h1 != h2
    assert len(h1) == 32
    assert claves.verificar(a1, "Clave#Segura2026", s1, h1)


def test_gastar_tiempo_calcula_un_pbkdf2(monkeypatch):
    llamadas = []
    monkeypatch.setattr(claves, "calcular", lambda algoritmo, clave, sal: llamadas.append(algoritmo) or b"")
    claves.gastar_tiempo("lo-que-sea")
    claves.gastar_tiempo(None)
    assert llamadas == ["PBKDF2_SHA256", "PBKDF2_SHA256"]


# --- política ---

@pytest.mark.parametrize("clave", ["Clave#Segura2026", "Ñandú.1234x", "aB3$aB3$aB", "Una frase larga 9!"])
def test_politica_acepta(clave):
    assert claves.error_politica(clave) is None


@pytest.mark.parametrize("clave, mensaje", [
    ("Ab1$", "La contraseña debe tener al menos 10 caracteres."),
    ("Aa1$" * 33, "La contraseña no puede superar 128 caracteres."),
    ("clave#segura2026", "La contraseña debe tener al menos una mayúscula."),
    ("CLAVE#SEGURA2026", "La contraseña debe tener al menos una minúscula."),
    ("Clave#Segura", "La contraseña debe tener al menos un número."),
    ("ClaveSegura2026", "La contraseña debe tener al menos un símbolo."),
    ("Clave Segura 2026", "La contraseña debe tener al menos un símbolo."),  # el espacio no cuenta como símbolo
])
def test_politica_rechaza(clave, mensaje):
    assert claves.error_politica(clave) == mensaje


def test_politica_rechaza_la_contrasena_por_defecto():
    # Admin@123456 tiene 12 caracteres, mayúscula, minúscula, número y símbolo: se rechaza aparte.
    assert claves.error_politica("Admin@123456") == "No puedes usar la contraseña por defecto."
