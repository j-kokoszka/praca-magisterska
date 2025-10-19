# .latexmkrc
$pdflatex = 'pdflatex %O %S';
$out_dir = 'out';
$aux_dir = 'temp';

# Optional: Ensure compilation uses the output directory
push @pdflatex_opts, "-output-directory=$out_dir";
