# .latexmkrc

# Ustawienie katalogu wyjściowego (zalecam trzymanie wszystkiego w jednym folderze)
$out_dir = 'out';
$aux_dir = 'out'; # Opcjonalne, ale bezpieczniej jest zakomentować i trzymać wszystko w out

# Konfiguracja PDF
$pdf_mode = 1; 
$pdflatex = 'pdflatex -synctex=1 -interaction=nonstopmode %O %S';

# Automatyczne uruchamianie bibera (dla biblatex)
$biber = 'biber %O %S';

# --- KONFIGURACJA GLOSSARIES (SŁOWNIKA) ---
# Latexmk nie obsługuje tego domyślnie, trzeba dodać niestandardową zależność:
add_cus_dep('glo', 'gls', 0, 'makeglossaries');
add_cus_dep('acn', 'acr', 0, 'makeglossaries');
sub makeglossaries {
    if ( $silent ) {
        system "makeglossaries -q \"$_[0]\"";
    }
    else {
        system "makeglossaries \"$_[0]\"";
    };
}
# ------------------------------------------

# Czyścimy również pliki generowane przez glossaries
$clean_ext .= ' glo gls glg acn acr alg';
