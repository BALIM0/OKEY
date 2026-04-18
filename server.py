import random
import json
import uuid
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

app = FastAPI()

RENKLER = ['Sarı', 'Mavi', 'Siyah', 'Kırmızı']
SAYILAR = list(range(1, 14))

def deste_olustur_ve_dagit(oyuncular_listesi):
    deste = [{'uid': str(uuid.uuid4()), 'renk': r, 'sayi': s, 'is_okey': False} for r in RENKLER for s in SAYILAR for _ in range(2)]
    deste.extend([{'uid': str(uuid.uuid4()), 'renk': 'Sahte', 'sayi': 'Okey', 'is_okey': False} for _ in range(2)])
    random.shuffle(deste)
    
    gosterge = next(tas for tas in deste if tas['renk'] != 'Sahte')
    okey_sayi = 1 if gosterge['sayi'] == 13 else gosterge['sayi'] + 1
    
    for tas in deste:
        if tas['renk'] == gosterge['renk'] and tas['sayi'] == okey_sayi:
            tas['is_okey'] = True
            
    oyuncular = {p: [] for p in oyuncular_listesi}
    oyuncular[oyuncular_listesi[0]] = [deste.pop() for _ in range(15)]
    oyuncular[oyuncular_listesi[1]] = [deste.pop() for _ in range(14)]
    oyuncular[oyuncular_listesi[2]] = [deste.pop() for _ in range(14)]
    oyuncular[oyuncular_listesi[3]] = [deste.pop() for _ in range(14)]
    
    return oyuncular, deste, gosterge, {'renk': gosterge['renk'], 'sayi': okey_sayi}

def gecerli_es_mi(grup, okey_degeri):
    if len(grup) < 3 or len(grup) > 4: return False
    referans_sayi = None
    kullanilan_renkler = set()
    for tas in grup:
        if tas.get('is_okey'): continue # OKEY JOKERDİR: Kontrol edilmeden atlanır
        
        # SAHTE OKEY KONTROLÜ: Sadece Okey taşının değerini alır
        r, s = (okey_degeri['renk'], okey_degeri['sayi']) if tas['renk'] == 'Sahte' else (tas['renk'], tas['sayi'])
        
        if referans_sayi is None: referans_sayi = s
        elif s != referans_sayi: return False
        if r in kullanilan_renkler: return False
        kullanilan_renkler.add(r)
    return True

def gecerli_seri_mi(grup, okey_degeri):
    if len(grup) < 3: return False
    renk = None
    for tas in grup:
        if not tas.get('is_okey'):
            r, _ = (okey_degeri['renk'], okey_degeri['sayi']) if tas['renk'] == 'Sahte' else (tas['renk'], tas['sayi'])
            if renk is None: renk = r
            elif r != renk: return False
            
    tas_sayilari = []
    okey_sayisi = sum(1 for tas in grup if tas.get('is_okey')) # Okeyleri sayıyoruz
    for tas in grup:
        if not tas.get('is_okey'):
            _, s = (okey_degeri['renk'], okey_degeri['sayi']) if tas['renk'] == 'Sahte' else (tas['renk'], tas['sayi'])
            tas_sayilari.append(s)
            
    if 1 in tas_sayilari and (13 in tas_sayilari or 12 in tas_sayilari):
        tas_sayilari = [14 if x == 1 else x for x in tas_sayilari]
        
    tas_sayilari.sort()
    for i in range(len(tas_sayilari) - 1):
        fark = tas_sayilari[i+1] - tas_sayilari[i]
        if fark == 0: return False # Seride aynı taştan iki tane olamaz
        okey_sayisi -= (fark - 1) # Okeyleri aradaki boşlukları doldurmak için harca
    return okey_sayisi >= 0

def cift_kontrol_et(el_taslari, okey_degeri):
    if len(el_taslari) != 14: return False
    okey_sayisi = sum(1 for tas in el_taslari if tas.get('is_okey'))
    normal_taslar = [tas for tas in el_taslari if not tas.get('is_okey')]
    frekans = {}
    for tas in normal_taslar:
        r, s = (okey_degeri['renk'], okey_degeri['sayi']) if tas['renk'] == 'Sahte' else (tas['renk'], tas['sayi'])
        anahtar = f"{r}-{s}"
        frekans[anahtar] = frekans.get(anahtar, 0) + 1
    tekli_tas_sayisi = sum(1 for adet in frekans.values() if adet % 2 != 0)
    return okey_sayisi >= tekli_tas_sayisi

def normal_bitis_kontrol(gruplar, okey_degeri):
    toplam_tas = sum(len(g) for g in gruplar)
    if toplam_tas != 14: return False
    for grup in gruplar:
        if not (gecerli_es_mi(grup, okey_degeri) or gecerli_seri_mi(grup, okey_degeri)):
            return False
    return True

class OyunYoneticisi:
    def __init__(self):
        self.aktif_baglantilar = {}
        self.oyuncular = [] 
        self.oyun_basladi_mi = False
        self.sira_kimde = None
        self.oyuncu_elleri = {}
        self.ortadaki_taslar = []
        self.atilan_taslar = {}
        self.gosterge = None
        self.okey_tasi = None

    async def baglan(self, websocket: WebSocket, oyuncu_adi: str):
        if self.oyun_basladi_mi:
            await websocket.accept()
            await websocket.send_json({"type": "baglanti_hatasi", "mesaj": "Masa şu an dolu ve oyun devam ediyor!"})
            await websocket.close()
            return
        if oyuncu_adi in self.oyuncular:
            await websocket.accept()
            await websocket.send_json({"type": "baglanti_hatasi", "mesaj": "Bu isimde biri var."})
            await websocket.close()
            return
        if len(self.oyuncular) >= 4:
            await websocket.accept()
            await websocket.send_json({"type": "baglanti_hatasi", "mesaj": "Masa dolu!"})
            await websocket.close()
            return

        await websocket.accept()
        self.oyuncular.append(oyuncu_adi)
        self.aktif_baglantilar[oyuncu_adi] = websocket
        self.atilan_taslar[oyuncu_adi] = []

        for ws in self.aktif_baglantilar.values():
            await ws.send_json({"type": "lobi", "oyuncular": self.oyuncular})

        if len(self.oyuncular) == 4:
            self.oyunu_baslat()
            await self.durumu_gonder()

    def oyunu_baslat(self):
        self.oyun_basladi_mi = True
        self.oyuncu_elleri, self.ortadaki_taslar, self.gosterge, self.okey_tasi = deste_olustur_ve_dagit(self.oyuncular)
        self.sira_kimde = self.oyuncular[0]
        for p in self.oyuncular:
            self.atilan_taslar[p] = []

    async def tumune_yayinla(self, mesaj: str):
        for ws in self.aktif_baglantilar.values():
            await ws.send_json({"type": "bilgi", "mesaj": mesaj})

    async def baglanti_koptu(self, oyuncu_adi: str):
        if oyuncu_adi in self.aktif_baglantilar: del self.aktif_baglantilar[oyuncu_adi]
        if oyuncu_adi in self.oyuncular: self.oyuncular.remove(oyuncu_adi)
        self.oyun_basladi_mi = False
        self.oyuncu_elleri = {}
        self.atilan_taslar = {p: [] for p in self.oyuncular}
        await self.tumune_yayinla(f"{oyuncu_adi} masadan kalktı. Oyun durdu.")
        for ws in self.aktif_baglantilar.values():
            await ws.send_json({"type": "lobi", "oyuncular": self.oyuncular})

    async def durumu_gonder(self):
        if not self.oyun_basladi_mi: return
        ust_taslar = {p: (self.atilan_taslar[p][-1] if self.atilan_taslar[p] else None) for p in self.oyuncular}

        for oyuncu_adi, ws in self.aktif_baglantilar.items():
            durum_paketi = {
                "type": "state",
                "oyuncular": self.oyuncular,
                "sira_kimde": self.sira_kimde,
                "benim_adim": oyuncu_adi,
                "gosterge": self.gosterge,
                "okey": self.okey_tasi, # DÜZELTME: Arayüzün bilebilmesi için Okey taşını pakete ekledik
                "eliniz": self.oyuncu_elleri[oyuncu_adi],
                "orta_tas_sayisi": len(self.ortadaki_taslar),
                "atilan_taslar": ust_taslar
            }
            await ws.send_json(durum_paketi)

    async def hamle_yap(self, oyuncu_adi: str, data: dict):
        if self.sira_kimde != oyuncu_adi:
            await self.aktif_baglantilar[oyuncu_adi].send_json({"type": "hata", "mesaj": "Sıra sizde değil!"})
            return

        islem = data.get("action")
        idx = self.oyuncular.index(oyuncu_adi)
        onceki_oyuncu = self.oyuncular[(idx - 1) % 4] 
        sonraki_oyuncu = self.oyuncular[(idx + 1) % 4] 

        if islem == "cek":
            nerden = data.get("nerden")
            if len(self.oyuncu_elleri[oyuncu_adi]) >= 15:
                await self.aktif_baglantilar[oyuncu_adi].send_json({"type": "hata", "mesaj": "Önce taş atmalısınız!"})
                return
            
            if nerden == "orta" and self.ortadaki_taslar:
                self.oyuncu_elleri[oyuncu_adi].append(self.ortadaki_taslar.pop())
                if len(self.ortadaki_taslar) == 0:
                    await self.tumune_yayinla("Ortada çekilecek taş kalmadı! El berabere bitti, masadaki taşlar yeniden dağıtılıyor.")
                    self.oyunu_baslat()
                    await self.durumu_gonder()
                    return
            elif nerden == "yandan":
                if self.atilan_taslar[onceki_oyuncu]:
                    self.oyuncu_elleri[oyuncu_adi].append(self.atilan_taslar[onceki_oyuncu].pop())
                else:
                    await self.aktif_baglantilar[oyuncu_adi].send_json({"type": "hata", "mesaj": "Çekilecek taş yok!"})
                    return
            
        elif islem == "at":
            tas_uid = data.get("tas_uid")
            if len(self.oyuncu_elleri[oyuncu_adi]) != 15:
                await self.aktif_baglantilar[oyuncu_adi].send_json({"type": "hata", "mesaj": "Önce taş çekmelisiniz!"})
                return
            atilan_tas = next((t for t in self.oyuncu_elleri[oyuncu_adi] if t['uid'] == tas_uid), None)
            if atilan_tas:
                self.oyuncu_elleri[oyuncu_adi].remove(atilan_tas)
                self.atilan_taslar[oyuncu_adi].append(atilan_tas)
                self.sira_kimde = sonraki_oyuncu 
                
        elif islem == "bit":
            tas_uid = data.get("tas_uid")
            gruplar_uid = data.get("gruplar") 
            
            if len(self.oyuncu_elleri[oyuncu_adi]) != 15:
                await self.aktif_baglantilar[oyuncu_adi].send_json({"type": "hata", "mesaj": "Bitmek için 15 taşınız olmalı!"})
                return
                
            atilan_tas = next((t for t in self.oyuncu_elleri[oyuncu_adi] if t['uid'] == tas_uid), None)
            if not atilan_tas: return
                
            el_kopyasi = self.oyuncu_elleri[oyuncu_adi].copy()
            el_kopyasi.remove(atilan_tas) 
            
            gruplar_obj = []
            for g_uids in gruplar_uid:
                g_obj = [next((t for t in el_kopyasi if t['uid'] == uid), None) for uid in g_uids]
                if all(g_obj): gruplar_obj.append(g_obj)

            if cift_kontrol_et(el_kopyasi, self.okey_tasi):
                await self.tumune_yayinla(f"🏆 TEBRİKLER! {oyuncu_adi} ÇİFTTEN BİTTİ!\nYeni el otomatik olarak başlatılıyor...")
                self.oyunu_baslat()
                await self.durumu_gonder()
                return
                
            if normal_bitis_kontrol(gruplar_obj, self.okey_tasi):
                await self.tumune_yayinla(f"🏆 TEBRİKLER! {oyuncu_adi} NORMAL BİTTİ!\nYeni el otomatik olarak başlatılıyor...")
                self.oyunu_baslat()
                await self.durumu_gonder()
                return
                
            await self.aktif_baglantilar[oyuncu_adi].send_json({"type": "hata", "mesaj": "Perleriniz hatalı! Bu dizilimle bitemezsiniz."})
            return 

        await self.durumu_gonder()

oyun = OyunYoneticisi()

@app.websocket("/ws/{oyuncu_adi}")
async def websocket_endpoint(websocket: WebSocket, oyuncu_adi: str):
    await oyun.baglan(websocket, oyuncu_adi)
    try:
        while True:
            data = await websocket.receive_text()
            await oyun.hamle_yap(oyuncu_adi, json.loads(data))
    except WebSocketDisconnect:
        await oyun.baglanti_koptu(oyuncu_adi)
