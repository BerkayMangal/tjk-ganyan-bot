#!/usr/bin/env python3
"""
TJK PDF Debug Tool
==================
Bir TJK PDF'ini indir ve raw content'i incele.
Parser'ı tune etmek için kullan.

Kullanım:
    python pdf_debug.py 08.03.2026 Istanbul
    python pdf_debug.py --local path/to/local.pdf
"""

import pdfplumber
import io
import sys
import json
from tjk_pdf_scraper import TJKPDFDownloader, HIPODROM_MAP


def inspect_pdf(pdf_bytes: bytes, output_dir: str = "debug_output"):
    """PDF'in raw yapısını incele."""
    import os
    os.makedirs(output_dir, exist_ok=True)
    
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        print(f"\n📄 PDF Info:")
        print(f"   Sayfa sayısı: {len(pdf.pages)}")
        print(f"   Metadata: {pdf.metadata}")
        
        for page_num, page in enumerate(pdf.pages):
            print(f"\n{'='*60}")
            print(f"📃 SAYFA {page_num + 1}")
            print(f"{'='*60}")
            
            # --- TEXT ---
            text = page.extract_text() or ""
            print(f"\n--- TEXT ({len(text)} karakter) ---")
            print(text[:2000])
            if len(text) > 2000:
                print(f"... ({len(text) - 2000} karakter daha)")
            
            # Text'i dosyaya kaydet
            with open(f"{output_dir}/page_{page_num+1}_text.txt", "w", encoding="utf-8") as f:
                f.write(text)
            
            # --- TABLES ---
            tables = page.extract_tables() or []
            print(f"\n--- TABLES ({len(tables)} tablo) ---")
            
            for t_idx, table in enumerate(tables):
                print(f"\n  Tablo {t_idx + 1}: {len(table)} satır x {len(table[0]) if table else 0} sütun")
                
                # İlk 5 satırı göster
                for r_idx, row in enumerate(table[:5]):
                    cleaned = [str(cell)[:25] if cell else "∅" for cell in row]
                    print(f"    [{r_idx}] {' | '.join(cleaned)}")
                
                if len(table) > 5:
                    print(f"    ... ({len(table) - 5} satır daha)")
                
                # Tabloyu JSON olarak kaydet
                with open(f"{output_dir}/page_{page_num+1}_table_{t_idx+1}.json", "w", encoding="utf-8") as f:
                    json.dump(table, f, ensure_ascii=False, indent=2)
            
            # --- WORDS (kelime konumları) ---
            words = page.extract_words() or []
            print(f"\n--- WORDS: {len(words)} kelime ---")
            if words[:5]:
                for w in words[:5]:
                    print(f"    ({w['x0']:.0f},{w['top']:.0f}) '{w['text']}'")
    
    print(f"\n✅ Debug çıktıları: {output_dir}/")
    print("   - page_N_text.txt: Her sayfanın raw text'i")
    print("   - page_N_table_M.json: Her tablonun JSON dump'ı")


def main():
    if "--local" in sys.argv:
        # Local PDF
        idx = sys.argv.index("--local")
        pdf_path = sys.argv[idx + 1]
        print(f"📂 Lokal PDF: {pdf_path}")
        with open(pdf_path, "rb") as f:
            pdf_bytes = f.read()
        inspect_pdf(pdf_bytes)
    
    elif len(sys.argv) >= 3:
        # Download + inspect
        date_str = sys.argv[1]
        hipodrom = sys.argv[2]
        
        print(f"📥 İndiriliyor: {date_str} - {hipodrom}")
        dl = TJKPDFDownloader()
        pdf_bytes = dl.download(date_str, hipodrom)
        
        if pdf_bytes:
            print(f"✅ {len(pdf_bytes)} bytes indirildi")
            inspect_pdf(pdf_bytes)
        else:
            print("❌ PDF alınamadı!")
            
            # Hangi hipodromlar var?
            print("\n🔍 Mevcut hipodromlar kontrol ediliyor...")
            found = dl.discover_hipodromlar(date_str)
            if found:
                print(f"✅ Bulunan: {', '.join(found)}")
            else:
                print("❌ Bu tarihte hiçbir hipodromda yarış yok")
    
    elif len(sys.argv) == 2:
        # Sadece tarih - tüm hipodromları tara
        date_str = sys.argv[1]
        print(f"🔍 {date_str} - Tüm hipodromlar taranıyor...")
        
        dl = TJKPDFDownloader()
        found = dl.discover_hipodromlar(date_str)
        
        if found:
            print(f"\n✅ Yarış bulunan hipodromlar: {', '.join(found)}")
            for hip in found:
                pdf_bytes = dl.download(date_str, hip)
                if pdf_bytes:
                    print(f"\n{'='*60}")
                    print(f"🏇 {hip}")
                    inspect_pdf(pdf_bytes, output_dir=f"debug_output/{hip}")
        else:
            print("❌ Hiçbir hipodromda yarış bulunamadı")
    
    else:
        print("Kullanım:")
        print("  python pdf_debug.py DD.MM.YYYY Hipodrom")
        print("  python pdf_debug.py DD.MM.YYYY           (tüm hipodromlar)")
        print("  python pdf_debug.py --local dosya.pdf")
        print()
        print("Hipodromlar:", ", ".join(HIPODROM_MAP.keys()))


if __name__ == "__main__":
    main()
