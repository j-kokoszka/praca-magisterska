# Praca Magisterska
Repozytorium zawierające kod używany w ramach pracy magisterskiej.

## Opis problemu
Współczesne aplikacje działające w środowiskach chmurowych, takich jak Kubernetes, wymagają mechanizmów 
elastycznego zarządzania zasobami, które umożliwiają utrzymanie wysokiej wydajności przy optymalnych kosztach. 
Klasyczne podejścia do automatycznego skalowania, takie jak Horizontal Pod Autoscaler (HPA) i Vertical 
Pod Autoscaler (VPA), oferują różne strategie adaptacji zasobów.

HPA umożliwia skalowanie liczby replik na podstawie metryk wydajnościowych, takich jak wykorzystanie CPU 
czy pamięci, natomiast VPA dostosowuje parametry pojedynczych kontenerów, zmieniając przydział zasobów 
bez zwiększania liczby instancji. Oba podejścia mają swoje zalety i ograniczenia:
- HPA sprawdza się w przypadku aplikacji stateless, ale może generować wysokie koszty przy nadmiernej 
liczbie replik.
- VPA lepiej działa w systemach stateful lub tych, gdzie poziom paralelizacji jest ograniczony, jednak 
jego działanie może być zbyt wolne lub mało elastyczne przy dużych wahaniach obciążenia.

W praktyce brakuje mechanizmu, który potrafiłby autonomicznie wybrać optymalną strategię skalowania w 
zależności od bieżących warunków systemowych i wymagań aplikacji. Operator Kubernetes implementujący 
taką funkcjonalność mógłby pełnić rolę autonomicznej pętli sterującej, dynamicznie przełączając się między 
HPA i VPA zgodnie z zdefiniowaną polityką decyzyjną (np. zdefiniowaną w Custom Resource Definition).

Taki system wymaga analizy:
- warunków, w których przełączenie między HPA i VPA jest uzasadnione,
- wpływu przełączeń na stabilność i dostępność aplikacji,
- sposobu formalizacji polityk sterowania w CRD,
- oraz oceny skuteczności operatora w środowisku symulacyjnym lub testowym.

## Teza
Implementacja autonomicznego operatora Kubernetes, zdolnego do dynamicznego wyboru między pionowym (VPA) a 
poziomym (HPA) skalowaniem na podstawie bieżących warunków obciążenia i zdefiniowanej polityki, pozwala 
zwiększyć efektywność wykorzystania zasobów oraz stabilność działania usług w środowiskach chmurowych.

## Cele pracy
1. Analiza istniejących mechanizmów autoskalowania w Kubernetes (HPA, VPA, KEDA, itp.) i ich ograniczeń.
2. Opracowanie modelu decyzyjnego dla autonomicznego wyboru strategii skalowania.
3. Implementacja operatora Kubernetes, który realizuje pętlę sterującą, pobierając politykę z CRD i dynamicznie 
aktywując HPA lub VPA.
4. Przeprowadzenie eksperymentów oceniających skuteczność podejścia w kontekście wydajności, stabilności i 
kosztów.
