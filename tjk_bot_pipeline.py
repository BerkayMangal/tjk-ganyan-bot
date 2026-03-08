#!/usr/bin/env python3
"""
TJK Bot Integration Layer
==========================
PDF scraper -> Feature Engineering -> ML Pipeline -> Telegram Bot

Bu modül scraper çıktısını ML pipeline'a ve Telegram bot'a bağlar.
"""

import pandas as pd
import numpy as np
from datetime import datetime
from typing import List, Optional, Dict, Tuple
from dataclasses import dataclass
from tjk_pdf_scraper import TJKScraper, RaceDay, Race, Horse


# ═══════════════════════════════════════════════════════════════
# FEATURE ENGINEERING
# ═══════════════════════════════════════════════════════════════

class FeatureEngineer:
    """
    Raw scraper data'sından ML feature'ları üret.
    
    Feature grupları:
    1. At form features (son_6 parse, trend, consistency)
    2. Jokey features (kazanma oranı, hipodrom uyumu)
    3. Mesafe/Pist features (at'ın mesafe geçmişi)
    4. Handikap/Kilo features
    5. Relative features (koşudaki diğer atlara göre)
    """
    
    @staticmethod
    def parse_son_6(son_6: str) -> Dict:
        """
        Son 6 performans string'ini feature'lara çevir.
        Örnek: "1-3-2-0-5-1" -> dict of features
        0 = koşmadı/bitiremedi
        """
        features = {
            'form_avg': 0.0,
            'form_best': 99,
            'form_worst': 0,
            'form_trend': 0.0,        # pozitif = iyileşiyor
            'form_consistency': 0.0,    # düşük = tutarlı
            'form_win_count': 0,
            'form_place_count': 0,      # ilk 3
            'form_active_count': 0,     # koştuğu yarış sayısı
            'form_score': 0.0,          # weighted composite
        }
        
        if not son_6 or son_6 == "-":
            return features
        
        # Parse
        parts = son_6.replace(' ', '').split('-')
        results = []
        for p in parts:
            try:
                val = int(p)
                results.append(val)
            except ValueError:
                results.append(0)
        
        if not results:
            return features
        
        # Aktif koşular (0 olmayan)
        active = [r for r in results if r > 0]
        features['form_active_count'] = len(active)
        
        if not active:
            return features
        
        features['form_avg'] = np.mean(active)
        features['form_best'] = min(active)
        features['form_worst'] = max(active)
        features['form_consistency'] = np.std(active) if len(active) > 1 else 0
        features['form_win_count'] = sum(1 for r in active if r == 1)
        features['form_place_count'] = sum(1 for r in active if r <= 3)
        
        # Trend: son yarışlar vs ilk yarışlar (negatif = iyileşiyor, derece düşüyor)
        if len(active) >= 3:
            recent = np.mean(active[:len(active)//2])
            earlier = np.mean(active[len(active)//2:])
            features['form_trend'] = earlier - recent  # pozitif = iyileşme
        
        # Composite score (düşük = daha iyi)
        # Ağırlıklı: son yarışlara daha fazla ağırlık
        weights = np.array([3, 2.5, 2, 1.5, 1, 0.5][:len(results)])
        weighted_results = []
        for i, r in enumerate(results):
            if r > 0 and i < len(weights):
                weighted_results.append(r * weights[i])
        
        if weighted_results:
            features['form_score'] = sum(weighted_results) / sum(weights[:len(weighted_results)])
        
        return features
    
    @staticmethod
    def compute_race_features(race: Race) -> pd.DataFrame:
        """
        Bir koşudaki tüm atlar için feature'ları hesapla.
        Relative features dahil (koşu içi karşılaştırma).
        """
        rows = []
        
        for horse in race.horses:
            # Base features
            row = {
                'at_no': horse.no,
                'at_adi': horse.ad,
                'yas': horse.yas,
                'kg': horse.kg,
                'mesafe': race.mesafe,
                'pist': race.pist,
                'handikap': horse.handikap,
                'ganyan_orani': horse.ganyan_orani,
            }
            
            # Form features
            form_features = FeatureEngineer.parse_son_6(horse.son_6)
            row.update(form_features)
            
            # Kilo advantage (düşük kilo = avantaj)
            row['kg_normalized'] = horse.kg if horse.kg > 0 else 55.0
            
            # Yaş penalty/bonus
            row['yas_prime'] = 1.0 if 3 <= horse.yas <= 5 else 0.5
            
            rows.append(row)
        
        df = pd.DataFrame(rows)
        
        if len(df) == 0:
            return df
        
        # --- RELATIVE FEATURES ---
        # Koşu ortalamasına göre
        if 'kg' in df.columns and df['kg'].sum() > 0:
            avg_kg = df[df['kg'] > 0]['kg'].mean()
            df['kg_relative'] = df['kg'] - avg_kg
        
        if 'form_score' in df.columns:
            avg_form = df['form_score'].mean()
            df['form_relative'] = avg_form - df['form_score']  # pozitif = formda
        
        # Ganyan rank (düşük oran = favori)
        if 'ganyan_orani' in df.columns and df['ganyan_orani'].sum() > 0:
            df['ganyan_rank'] = df['ganyan_orani'].rank(method='min')
        
        # Field size
        df['field_size'] = len(df)
        
        return df
    
    @staticmethod
    def compute_rating(row: pd.Series) -> float:
        """
        Tek at için composite rating hesapla.
        0-100 arası, yüksek = daha iyi.
        
        Ağırlıklar:
        - Form: 35%
        - Jokey: 20% (şimdilik placeholder)
        - Kilo: 15%
        - Yaş: 10%
        - Ganyan: 20%
        """
        score = 50.0  # Base
        
        # Form component (0-35 puan)
        form_score = row.get('form_score', 0)
        if form_score > 0:
            # form_score düşük = iyi, 1=birinci 
            form_component = max(0, 35 - (form_score - 1) * 7)
            score += form_component - 17.5  # center around 0
        
        form_trend = row.get('form_trend', 0)
        score += min(5, max(-5, form_trend * 3))  # trend bonus/penalty
        
        # Kilo component
        kg_relative = row.get('kg_relative', 0)
        score -= kg_relative * 2  # hafif at = bonus
        
        # Yaş component
        yas_prime = row.get('yas_prime', 0.5)
        score += (yas_prime - 0.5) * 10
        
        # Ganyan implied probability
        ganyan = row.get('ganyan_orani', 0)
        if ganyan > 0:
            implied_prob = 1 / ganyan
            score += implied_prob * 40  # max ~20 puan
        
        # Clamp
        return max(0, min(100, score))


# ═══════════════════════════════════════════════════════════════
# ALTILI GANYAN KUPON MOTORU
# ═══════════════════════════════════════════════════════════════

@dataclass
class KuponAyak:
    kosu_no: int
    atlar: List[int]         # at numaraları
    banko: bool = False      # tek at = banko
    ratings: Dict[int, float] = None  # at_no -> rating

@dataclass
class Kupon:
    tip: str                 # "konservatif", "dengeli", "agresif"
    ayaklar: List[KuponAyak] = None
    kombinasyon: int = 0
    maliyet: float = 0.0
    
    def hesapla(self, birim_fiyat: float = 1.0):
        if not self.ayaklar:
            return
        self.kombinasyon = 1
        for ayak in self.ayaklar:
            self.kombinasyon *= len(ayak.atlar)
        self.maliyet = self.kombinasyon * birim_fiyat


class KuponMotoru:
    """
    Rating'lere göre altılı ganyan kuponu oluştur.
    
    3 strateji:
    - Konservatif: Bankolu, az kombinasyon (10-50 TL)
    - Dengeli: Karma, orta kombinasyon (50-200 TL)
    - Agresif: Geniş, çok kombinasyon (200-500 TL)
    """
    
    STRATEGIES = {
        'konservatif': {
            'banko_threshold': 75,    # 75+ rating = banko
            'min_at': 1,
            'max_at': 3,
            'max_kombinasyon': 100,
        },
        'dengeli': {
            'banko_threshold': 80,
            'min_at': 2,
            'max_at': 4,
            'max_kombinasyon': 500,
        },
        'agresif': {
            'banko_threshold': 85,
            'min_at': 3,
            'max_at': 6,
            'max_kombinasyon': 2000,
        },
    }
    
    def generate(self, race_day: RaceDay, strategy: str = 'dengeli') -> Kupon:
        """Kupon oluştur."""
        config = self.STRATEGIES[strategy]
        kupon = Kupon(tip=strategy, ayaklar=[])
        
        fe = FeatureEngineer()
        
        # Altılı ayaklarını bul
        altili_races = [r for r in race_day.races if r.altili_ayak > 0]
        altili_races.sort(key=lambda r: r.altili_ayak)
        
        if len(altili_races) != 6:
            # Altılı işaretlenmemişse son 6 koşuyu al
            altili_races = race_day.races[-6:] if len(race_day.races) >= 6 else race_day.races
        
        for race in altili_races:
            if not race.horses:
                continue
            
            # Feature'ları hesapla
            df = fe.compute_race_features(race)
            
            # Rating hesapla
            df['rating'] = df.apply(fe.compute_rating, axis=1)
            df = df.sort_values('rating', ascending=False)
            
            # At seçimi
            ratings_dict = dict(zip(df['at_no'].astype(int), df['rating']))
            
            top_rating = df['rating'].iloc[0] if len(df) > 0 else 0
            
            if top_rating >= config['banko_threshold']:
                # Banko
                selected = [int(df['at_no'].iloc[0])]
                is_banko = True
            else:
                # Rating'e göre seç
                n_select = min(config['max_at'], len(df))
                
                # Minimum rating threshold: top rating'in %70'i
                min_rating = top_rating * 0.7
                eligible = df[df['rating'] >= min_rating]
                
                n_select = max(config['min_at'], min(n_select, len(eligible)))
                selected = eligible['at_no'].head(n_select).astype(int).tolist()
                is_banko = len(selected) == 1
            
            kupon.ayaklar.append(KuponAyak(
                kosu_no=race.kosu_no,
                atlar=selected,
                banko=is_banko,
                ratings=ratings_dict
            ))
        
        kupon.hesapla()
        
        # Kombinasyon çok fazlaysa kıs
        if kupon.kombinasyon > config['max_kombinasyon']:
            kupon = self._trim_kupon(kupon, config['max_kombinasyon'])
        
        return kupon
    
    def _trim_kupon(self, kupon: Kupon, max_komb: int) -> Kupon:
        """Kombinasyonu azaltmak için en düşük rating'li atları çıkar."""
        while kupon.kombinasyon > max_komb:
            # En çok atlı (banko olmayan) ayağı bul
            non_banko = [a for a in kupon.ayaklar if not a.banko and len(a.atlar) > 1]
            if not non_banko:
                break
            
            # En geniş ayaktan en düşük rating'li atı çıkar
            widest = max(non_banko, key=lambda a: len(a.atlar))
            if widest.ratings:
                worst = min(widest.atlar, key=lambda no: widest.ratings.get(no, 0))
                widest.atlar.remove(worst)
            else:
                widest.atlar.pop()
            
            if len(widest.atlar) == 1:
                widest.banko = True
            
            kupon.hesapla()
        
        return kupon
    
    def format_telegram(self, kupon: Kupon, race_day: RaceDay) -> str:
        """Telegram mesajı formatında kupon."""
        emoji_map = {
            'konservatif': '🔵',
            'dengeli': '🟡', 
            'agresif': '🔴',
        }
        
        lines = [
            f"{emoji_map.get(kupon.tip, '⚪')} ALTILI GANYAN - {kupon.tip.upper()}",
            f"📍 {race_day.hipodrom} | {race_day.tarih}",
            f"{'─' * 28}",
        ]
        
        for ayak in kupon.ayaklar:
            banko_tag = " 🎯BANKO" if ayak.banko else ""
            at_str = "-".join(str(a) for a in sorted(ayak.atlar))
            
            # Rating'leri göster
            rating_str = ""
            if ayak.ratings:
                top_at = max(ayak.atlar, key=lambda no: ayak.ratings.get(no, 0))
                top_rating = ayak.ratings.get(top_at, 0)
                rating_str = f" (R:{top_rating:.0f})"
            
            lines.append(
                f"  {ayak.kosu_no}. Koşu: [{at_str}]{banko_tag}{rating_str}"
            )
        
        lines.extend([
            f"{'─' * 28}",
            f"📊 Kombinasyon: {kupon.kombinasyon}",
            f"💰 Maliyet: {kupon.maliyet:.0f} TL",
        ])
        
        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# FULL PIPELINE
# ═══════════════════════════════════════════════════════════════

def run_pipeline(date_str: str, hipodrom: str) -> str:
    """
    Tam pipeline: PDF -> Parse -> Feature -> Rating -> Kupon -> Telegram
    """
    scraper = TJKScraper()
    fe = FeatureEngineer()
    kupon_motoru = KuponMotoru()
    
    # 1. PDF indir + parse
    print(f"📥 PDF çekiliyor: {date_str} - {hipodrom}")
    race_day = scraper.get_altili_ganyan(date_str, hipodrom)
    
    if not race_day or not race_day.races:
        return f"❌ {hipodrom}'da yarış verisi bulunamadı"
    
    print(f"✅ {len(race_day.races)} koşu parse edildi")
    
    # 2. Her koşu için rating hesapla
    output_lines = [
        f"🏇 {race_day.hipodrom} - {race_day.tarih}",
        f"{'═' * 40}",
        "",
    ]
    
    for race in race_day.races:
        if not race.horses:
            continue
        
        df = fe.compute_race_features(race)
        df['rating'] = df.apply(fe.compute_rating, axis=1)
        df = df.sort_values('rating', ascending=False)
        
        altili_tag = f" [ALTILI {race.altili_ayak}. AYAK]" if race.altili_ayak else ""
        
        output_lines.append(f"🏁 {race.kosu_no}. KOŞU{altili_tag}")
        output_lines.append(f"   📏 {race.mesafe}m | 🏟️ {race.pist} | ⏰ {race.saat}")
        
        for _, row in df.head(5).iterrows():
            rating = row['rating']
            bar = '█' * int(rating / 10) + '░' * (10 - int(rating / 10))
            
            form_str = f"F:{row.get('form_score', 0):.1f}" if row.get('form_score', 0) > 0 else "F:-"
            
            output_lines.append(
                f"   {int(row['at_no']):2d}. {row['at_adi']:<18s} "
                f"R:{rating:5.1f} [{bar}] {form_str}"
            )
        
        output_lines.append("")
    
    # 3. Kuponlar
    output_lines.append(f"{'═' * 40}")
    output_lines.append("🎫 KUPONLAR")
    output_lines.append(f"{'═' * 40}\n")
    
    for strategy in ['konservatif', 'dengeli', 'agresif']:
        kupon = kupon_motoru.generate(race_day, strategy)
        output_lines.append(kupon_motoru.format_telegram(kupon, race_day))
        output_lines.append("")
    
    return "\n".join(output_lines)


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys
    
    date_str = sys.argv[1] if len(sys.argv) > 1 else datetime.now().strftime("%d.%m.%Y")
    hipodrom = sys.argv[2] if len(sys.argv) > 2 else "Istanbul"
    
    result = run_pipeline(date_str, hipodrom)
    print(result)
