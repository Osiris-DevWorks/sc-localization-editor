# Smart Citizen : guide de démarrage rapide

> Cette page est une traduction fournie pour votre confort. En cas de divergence, la version anglaise fait foi. Statut des traductions : `languages/TRANSLATIONS.md`.

## Première configuration

Au lancement, Smart Citizen recharge les personnalisations de votre session précédente et recherche votre installation de Star Citizen : l'installateur préremplit ce chemin, mais vous pouvez le modifier dans l'onglet **Paramètres**. Toutes les données de localisation et DataForge proviennent **directement de votre `Data.p4k` installé** (aucun téléchargement, aucun miroir communautaire), donc une extraction initiale est obligatoire après l'installation ou après chaque patch du jeu.

## Mode Simple et mode Avancé

Smart Citizen s'ouvre dans l'un de deux modes, et vous pouvez changer à tout moment.

- Le **mode Simple** est un écran à deux boutons : le premier, **Appliquer les enrichissements**, exécute toute la chaîne avec vos réglages actuels (extraction, génération, application, avec une sauvegarde préalable de votre fichier de jeu) ; le second bascule en **mode Avancé**. C'est la voie rapide quand vous voulez simplement appliquer les enrichissements sans retoucher les textes à la main.
- Le **mode Avancé** est l'application complète : le tableau de textes, les filtres, l'onglet Enrichissements, l'onglet Paramètres, et tout le reste de ce guide.

Choisissez votre mode par défaut à l'installation, ou basculez de l'un à l'autre depuis l'application. Le mode Simple utilise les derniers réglages enregistrés en mode Avancé.

## 1. Extraire la localisation de base depuis Data.p4k

Ouvrez l'onglet **Paramètres** et cliquez sur **Extraire depuis Data.p4k**. Cela décompresse le `global.ini` d'origine ainsi que les XML d'entités DataForge utilisés par le générateur d'enrichissements : vaisseaux, composants, armes, missions, plans de fabrication, etc.

Une fois l'extraction terminée, le `base.ini` extrait est chargé automatiquement dans le tableau, fusionné avec les fichiers d'enrichissements et vos modifications enregistrées dans `user.ini`.

## 2. Modifier les textes de localisation

- Double-cliquez sur une cellule **Valeur personnalisée** pour modifier le texte.
- **Valeur par défaut** : texte d'origine du `base.ini` extrait de `Data.p4k`.
- **Valeur actuelle** : la valeur effective avant votre modification (base + couches INI importées).
- **Valeur personnalisée** : votre modification personnelle. Enregistrée automatiquement à chaque changement et conservée dans `<dossier de données>\<canal>\user.ini` (le dossier de données par défaut est `Documents\Smart Citizen`, et chaque canal de Star Citizen, LIVE, PTU, EPTU, HOTFIX, TECH-PREVIEW, a ses propres modifications isolées).
- La colonne **Statut** indique la provenance de la valeur actuelle de chaque ligne :
  - **Modifié** : vous avez explicitement modifié la Valeur personnalisée.
  - **Enrichi** : généré automatiquement par le pipeline d'enrichissements (surcouches de stats, balises de plans, etc.).
  - **Inchangé** : texte d'origine du `base.ini`.
  - **Nouveau** : la clé n'existe que dans vos modifications ou dans le pipeline d'enrichissements, pas dans le `base.ini` d'origine.

## 3. Panneau d'aperçu

Le **panneau d'aperçu** en haut à droite affiche le rendu du texte de la ligne sélectionnée. Les jetons de localisation du jeu sont traduits en HTML stylisé pour donner un aperçu proche du rendu en jeu :

- `\n` → saut de ligne
- `<EM3>...</EM3>` → titre de section souligné
- `<EM4>...</EM4>` → emphase en gras bleu (généralement des valeurs de stats)
- `~mission(Name)` → libellé `[Name]` grisé (le jeu substitue la valeur réelle à l'exécution)

Le panneau reste visible dans tous les onglets et reflète la dernière ligne sélectionnée dans l'**Éditeur de textes** : pratique pour vérifier la mise en forme d'une longue description de mission ou d'une entrée de journal avant d'appliquer.

## 4. Catégories

Utilisez le filtre **Catégorie** pour vous concentrer sur un domaine :

- **Ships** : noms et descriptions de vaisseaux (`vehicle_Name*`, `vehicle_Desc*`, plus les variantes Wikelo/Collector).
- **Ship Items** : boucliers, générateurs, refroidisseurs, moteurs quantiques, moteurs de saut, armes de vaisseau, missiles, bombes, tourelles.
- **Missions** : briefings de mission, textes de contrats, descriptions de récompenses.
- **Gear** : armes FPS, armures, casques, combinaisons, optiques.
- **Commodities** : marchandises et matériaux de fabrication.
- **Journal** : entrées de journal en jeu, style Galactapedia.
- **Other** : tout le reste.

## 5. Recherche et filtres

- Utilisez la **zone de recherche** pour trouver des textes par clé ou par contenu.
- Combinez avec les filtres **Catégorie** et **Statut** (Modifié / Enrichi / Inchangé / Nouveau).
- Cochez **Masquer les inchangés** pour ne voir que vos propres modifications.
- Les **champs de filtre par colonne** sous chaque en-tête affinent la recherche dans le tableau.
- Cliquez sur un en-tête de colonne pour trier. Cliquez sur l'en-tête **★** pour remonter les favoris en haut.

## 6. Vaisseaux favoris

- Cliquez sur la colonne **★** d'une ligne de vaisseau pour le marquer comme favori.
- Les vaisseaux favoris reçoivent un préfixe configurable devant leur nom, ce qui les fait remonter en tête de la liste de vaisseaux en jeu.
- Changez le caractère de préfixe dans l'onglet **Enrichissements** (par défaut : `*`).

## 7. Appliquer les modifications au jeu

Cliquez sur **Appliquer les enrichissements** pour écrire vos modifications dans l'installation du jeu. Une sauvegarde horodatée du `global.ini` actuel est créée dans `<dossier de données>\<canal>\backups\` avant toute écriture.

La couleur du bouton vous indique où vous en êtes : **rouge** signifie que quelque chose a changé depuis votre dernière application (une modification, une régénération, un changement de langue ou de canal) et que le jeu ne l'a pas encore ; **vert** signifie que le jeu correspond déjà à ce qui est chargé, et le bouton reste désactivé puisqu'il n'y a rien à refaire. La même convention rouge/vert s'applique à **Générer les enrichissements** et **Appliquer les modifications d'étiquettes** dans l'onglet Enrichissements. Si vous fermez l'application alors que le bouton Appliquer est encore rouge, Smart Citizen vous demande s'il faut appliquer maintenant ou quitter sans appliquer, pour qu'aucun travail non appliqué ne se perde en silence.

Smart Citizen ajoute aussi un petit filigrane à la version affichée par le lanceur (`Frontend_PU_Version`), en ajoutant `| Localizations Enhanced with Smart Citizen v{VERSION}`. C'est ainsi que vous pouvez confirmer en jeu que votre loc-pack est actif : regardez l'étiquette de version sur le menu principal de Star Citizen. Le filigrane est réécrit à chaque application, il ne s'accumule donc jamais d'une version à l'autre.

## 8. Restaurer une sauvegarde

Ouvrez le menu **Plus** de la barre d'outils et choisissez **Restaurer une sauvegarde** pour revenir à une version précédente. Smart Citizen conserve jusqu'à **5 sauvegardes automatiques** ; la plus ancienne est supprimée à mesure que de nouvelles sont créées.

## 9. Effacer la localisation

Ouvrez le menu **Plus** et choisissez **Effacer la localisation** pour supprimer le `global.ini` personnalisé du répertoire du jeu et revenir au texte par défaut (d'origine). Vos modifications enregistrées dans `<dossier de données>\<canal>\user.ini` sont intactes et peuvent être réappliquées à tout moment.

## 10. Importer un INI

Utilisez **Importer un INI** dans l'onglet **Paramètres** (aussi disponible dans le menu **Plus** de la barre d'outils) pour fusionner un fichier INI existant dans vos modifications. Une boîte de dialogue de résolution de conflits vous laisse décider, clé par clé : **conserver la valeur actuelle**, **utiliser la valeur importée**, **ajouter après**, **ajouter avant**, ou saisir une valeur **personnalisée**.

## 11. Exporter un Loc-Pack

Ouvrez le menu **Plus** et choisissez **Exporter un INI…** pour regrouper le `global.ini` actuellement appliqué dans un zip unique, `SmartCitizen-LocPack-{canal}-{AAAAMMJJ}.zip`, que n'importe qui peut déposer dans son dossier `StarCitizen\<canal>\data\Localization\english\` pour utiliser le même loc-pack sans installer Smart Citizen. Pratique pour partager des préréglages avec des amis ou votre organisation.

## 12. Réinitialiser user.ini

Utilisez **Réinitialiser user.ini** dans l'onglet **Paramètres** pour effacer toutes vos modifications personnelles du canal actif. Une demande de confirmation évite les faux clics, et une sauvegarde automatique du `user.ini` actuel est d'abord placée dans `<dossier de données>\<canal>\backups\` : une réinitialisation reste donc récupérable si vous changez d'avis.

## 13. Après les mises à jour du jeu

Quand Star Citizen est mis à jour, vos modifications sont préservées dans `<dossier de données>\<canal>\user.ini`. Relancez **Extraire depuis Data.p4k** pour récupérer les textes d'origine du jeu patché : le tableau se recharge automatiquement et vos personnalisations se réappliquent par-dessus.

## 14. Changer de langue

Choisissez une langue dans le menu **Langue** de l'onglet **Paramètres** (à côté de Canal). Le changement porte à la fois sur l'interface de l'application et sur les textes du jeu dans le tableau :

- **L'anglais** (par défaut) utilise les textes d'origine extraits de votre propre `Data.p4k`.
- **Les autres langues** téléchargent le `global.ini` traduit par la communauté pour cette langue et le superposent à la base anglaise : tout texte non couvert par la traduction retombe sur l'anglais au lieu de disparaître. Le téléchargement est mis en cache par langue ; revenir à une langue déjà utilisée réutilise le cache.
- **Les enrichissements restent en anglais.** Les blocs de stats, balises et détails de mission sont générés depuis les données du jeu et gardent leur forme anglaise au-dessus de la prose traduite. Une ligne mixte (par exemple un nom de rôle en français dans un bloc de stats anglais) est un comportement attendu, pas un bug.
- **Associer un fichier de langue** (onglet Paramètres) permet de pointer une langue vers une autre URL de `global.ini`, par exemple votre propre fork d'une traduction communautaire. Votre URL l'emporte sur la valeur par défaut intégrée.
- Certains textes de l'interface ne se mettent à jour qu'après un redémarrage de l'application. Les textes du tableau se rechargent immédiatement.

L'application écrit dans le dossier de langue correspondant de votre installation du jeu et règle `g_language` dans `user.cfg`, pour que le jeu charge le bon fichier.

Envie d'aider à traduire ? L'état des traductions par langue est suivi dans `languages/TRANSLATIONS.md` du dépôt, et nous préférons de loin vos mots à ceux d'une machine. Contactez-nous sur le Discord.

## 15. Mises à jour de l'application

Smart Citizen vérifie l'existence d'une nouvelle version à chaque démarrage. Quand une mise à jour est disponible, les notes de version s'affichent dans une fenêtre défilante avec deux choix :

- **Mettre à jour maintenant** télécharge le nouvel installateur, Windows demande l'autorisation, puis Smart Citizen se ferme, se met à jour et se rouvre sur la nouvelle version. Vos modifications, sauvegardes et réglages sont intacts.
- **Plus tard** vous laisse sur la version actuelle ; la question reviendra au prochain lancement.

Vous pouvez aussi vérifier manuellement à tout moment avec **Vérifier les mises à jour** dans l'onglet Paramètres. Les versions portables affichent à la place un bouton **Ouvrir la page de version**, puisqu'il n'y a pas d'installateur à exécuter : téléchargez le nouveau zip et décompressez-le par-dessus l'ancien dossier.

## Onglet Enrichissements

- Activez les surcouches de stats qui ajoutent des données chiffrées aux descriptions : vitesse SCM, PV de bouclier, DPS, capacité de soute, stats de faisceau des lasers de minage (Fracture / Extraction), rendements des outils de récupération portatifs, listes de plans, XP de mission, et plus. L'XP de mission nomme aussi la voie de réputation qu'elle alimente (ex. : `750 XP (Hauling)`), les contrats de scan/minage de Battaglia portent une balise `[RS ####]` avec la signature de ressource de base du minerai ciblé, et le journal Mining Compendium liste la RS de base de chaque minerai à côté de ses lieux d'extraction.
- **Consommables médicaux** : ajoute une ligne d'effet en langage clair aux injecteurs CureLife de base (MedPen, OxyPen, AdrenaPen et compagnie), pour que la description dise ce que fait réellement l'injecteur au lieu de se limiter à son texte d'ambiance.
- **Afficher les stats au-dessus de la description** : placez le bloc de stats en tête de description plutôt qu'en bas, pour que les chiffres soient la première chose lue en jeu.
- Activez ou désactivez chaque catégorie d'enrichissements indépendamment.
- Configurez le caractère de préfixe des vaisseaux favoris.
- **Le suivi des plans possédés** a déménagé dans son propre onglet **Suivi des plans** ; voir la section suivante.
- **Générateur d'étiquettes** : personnalisez les balises entre crochets placées sur les noms de composants, missiles, armes de vaisseau et marchandises. Réordonnez les éléments avec ▲/▼, désactivez des éléments individuels, changez la longueur des abréviations (`M` / `MIL` / `Military`), choisissez le séparateur (aucun, tiret, espace, etc.) et les crochets (carrés, ronds, aucun, etc.), et placez la balise avant ou après le nom. Les composants disposent aussi d'un élément **Type** optionnel (Bouclier, Refroidisseur, Générateur, etc.), désactivé par défaut. Les marchandises ont un élément **Usage** qui montre à quoi servent leurs matériaux de fabrication. Cliquez sur **Appliquer les modifications d'étiquettes** pour enregistrer et régénérer. (**Générer les enrichissements** enregistre aussi d'abord toute modification d'étiquette en attente, pour qu'un réglage non enregistré ne puisse pas échapper à une régénération.)
- **Titres de mission** (onglet Générateur d'étiquettes) : faites précéder les titres des missions de transport par leur itinéraire. Choisissez le placement (avant, après, ou en remplacement du titre), la flèche d'itinéraire (`>`, `->`, `to`, ou les formes `->-`/`->=`/`=>-`/`=>=` qui distinguent un point unique de plusieurs à chaque extrémité), le séparateur de titre, et le niveau de détail du lieu (adresse complète par défaut ; le nom court peut ne pas s'afficher sur de rares missions), avec un aperçu en direct. Une course de transport se lit alors `Area18 > Lorville - <titre d'origine>`, pour voir le trajet d'un coup d'œil dans la liste de contrats, et les transports multi-étapes listent leurs destinations (`Area18 > Lorville, New Babbage`). Deux options indépendantes raccourcissent le titre d'origine : **Raccourcir les titres d'origine** applique des abréviations de formules choisies (par ex. « Local Shipment Route » → « Route », plus la gestion des préfixes de rang et de la famille Ling), et **Raccourcir les tailles de cargaison** abrège les tailles (« Extra Small » → « XS »). Des cases individuelles affinent encore : supprimer « Cargo » ou « Haul », retirer « Rank », ou souligner les transports « Direct » pour les mettre en valeur, pour que l'itinéraire et les balises tiennent même sur les titres longs.
- **Étiquettes de mission** : personnalisez les en-têtes de section des blocs d'enrichissement de mission (MISSION DETAILS, POTENTIAL BLUEPRINTS, ITEM REWARDS, BLUEPRINT DATA), le libellé d'XP affiché sur les missions sans rang de réputation spécifique (par défaut « Rep »), et la balise d'emphase (EM3 = souligné, EM4 = couleur) des en-têtes.
- **Champs des détails de mission** : affichez ou masquez individuellement chaque ligne du bloc MISSION DETAILS (type de mission, difficulté, apparitions, réputation, plans, et la balise de titre `[BP]`), pour que vos descriptions de mission ne portent que les données qui vous intéressent.
- Cliquez sur **Générer les enrichissements** pour extraire les données DataForge de `Data.p4k` et reconstruire les fichiers INI d'enrichissements. Les correctifs déclaratifs de `patches/` sont réappliqués de façon idempotente à chaque régénération, pour que les bugs de données connus de CIG restent corrigés sans attendre un patch du jeu.

## Onglet Suivi des plans

Suivez les plans de fabrication que vous possédez déjà, et retrouvez cette information en jeu : les objets possédés reçoivent une balise bleue `[Owned]` dans les listes POTENTIAL BLUEPRINTS des missions, pour voir d'un coup d'œil dans un contrat ce qu'il vous reste à chasser.

- **Deux listes, une navette.** Les plans disponibles à gauche, votre collection à droite. Sélectionnez des éléments et déplacez-les avec les boutons fléchés. La collection persiste entre les sessions.
- **Trouvez vite.** Une zone de recherche filtre les deux listes, et les filtres **Mission / Type / Classe / Taille / Grade** réduisent la liste des disponibles selon la mission d'origine du plan et le type d'objet (armure, arme FPS, équipement de vaisseau, etc.).
- **Rechercher les plans possédés dans les journaux** remplit la collection automatiquement : la fonction lit les fichiers journaux de Star Citizen pour repérer les plans reçus en jeu et les marque comme possédés. Seuls les plans reçus depuis la dernière recherche sont importés, donc la relancer à tout moment ne coûte rien. Elle nécessite que le chemin d'installation de Star Citizen soit renseigné dans l'onglet Paramètres.
- **Appliquer les étiquettes [Owned]** retisse les balises `[Owned]` dans vos textes chargés après un changement de collection. Comme les autres boutons d'action, il passe au **rouge** quand votre collection contient des changements que le tableau n'a pas encore intégrés, et au **vert** une fois tout synchronisé.
- La colonne **Possédé** du tableau de textes affiche toujours une étoile et trie les possédés en premier, mais elle est désormais en lecture seule ; la collection se gère depuis cet onglet.

## Onglet Paramètres

- **Apparence** : choisissez le thème de l'application (voir plus bas).
- **Installation de Star Citizen** : chemin vers votre répertoire LIVE ; détecté automatiquement à l'installation, modifiable ici. Le menu **Canal** choisit le canal que l'application lit et écrit, et le menu **Langue** change la langue de l'application et des textes du jeu (voir *Changer de langue* plus haut).
- **Données Smart Citizen** : dossier pour `user.ini`, les caches, l'extraction DataForge, les INI d'enrichissements générés et les sauvegardes. Par défaut `Documents\Smart Citizen` ; déplacez-le hors de OneDrive si l'extraction ou le nettoyage du cache est lent.
- **Localisation de base (extraction P4K)** : cliquez sur **Extraire depuis Data.p4k** pour décompresser la localisation d'origine et les données d'entités DataForge directement depuis votre jeu installé. C'est l'unique source des textes de base et des données d'enrichissements.
- **Importer un INI** : fusionnez un fichier INI existant dans vos modifications via la boîte de dialogue de résolution de conflits.
- **Réinitialiser user.ini** : effacez toutes vos modifications personnelles du canal actif. Demande confirmation et sauvegarde automatiquement le `user.ini` actuel avant l'effacement.
- **Restaurer user.ini** : ramenez vos modifications personnelles à un instantané antérieur. Smart Citizen conserve des sauvegardes tournantes de `user.ini` (jusqu'à 5, prises automatiquement avant chaque changement) : si un import ou une modification tourne mal, choisissez une version précédente et récupérez vos textes. La restauration est elle-même réversible : le fichier actuel est d'abord sauvegardé.

## Onglet Journal

- Journal d'application en temps réel.
- Filtrez par niveau, activez le défilement automatique, et **exportez** le journal pour le dépannage ou les rapports de bug.

## Thèmes

Choisissez un thème dans **Paramètres → Apparence** :

- **Défaut** : SCLE, un thème cyber bleu nuit inspiré de l'interface mobiGlas de Star Citizen.
- **Clair / Sombre** : thèmes d'interface classiques.
- **ODW** : signature Osiris DevWorks, anthracite marine et or antique.

## Barre d'état

Affiche le nombre d'entrées chargées / modifiées et l'état de tout traitement en arrière-plan (extraction, génération, application).

## Visite guidée

Cliquez sur le bouton **Tutoriel** de la barre d'outils à tout moment pour rejouer la visite guidée : un parcours pas à pas du flux de travail principal avec des info-bulles pointant chaque contrôle. La visite se lance aussi automatiquement au premier lancement d'une nouvelle version, pour qu'une installation fraîche ne démarre jamais à froid. Cliquez sur **Passer** à tout moment pour la fermer.

## Onglet FAQ

L'onglet **FAQ** répond aux questions qu'on nous pose le plus souvent, directement dans l'application : quels fichiers Smart Citizen touche, si l'on risque un bannissement en l'utilisant, pourquoi Windows signale l'installateur, et comment annuler ses modifications. Consultez-le d'abord ; si votre question n'y figure pas, le Discord est à un clic.

## Raccourcis clavier

- **Ctrl+Shift+C** : copier les lignes filtrées dans le presse-papiers (format clé=valeur).

## Dépannage

- **Tableau vide** : vérifiez que **Extraire depuis Data.p4k** s'est terminé et que le rechargement post-extraction est fini, puis consultez l'onglet **Journal** pour les erreurs d'analyse.
- **Enrichissements vides ou incomplets** : lancez **Générer les enrichissements** depuis l'onglet Enrichissements ; cela nécessite un cache DataForge (cliquez d'abord sur **Extraire depuis Data.p4k** si ce n'est pas déjà fait).
- **Échec d'Appliquer les enrichissements** : vérifiez le chemin d'installation de Star Citizen dans l'onglet **Paramètres** et que le jeu n'est pas en cours d'exécution.
- **Données obsolètes après une mise à jour du jeu** : relancez **Extraire depuis Data.p4k**, puis régénérez les enrichissements.

## Problèmes connus

Certaines anomalies de texte de mission proviennent des données de Star Citizen elles-mêmes (références de clés de localisation erronées dans les enregistrements de contrats de CIG). Le jeu lit les contrats depuis son propre `Data.p4k` à l'exécution, donc Smart Citizen ne peut pas changer quelle clé le jeu consulte : il ne peut modifier que le *texte* de chaque clé. Quand c'est possible, nous contournons ces bugs en fusionnant le contenu prévu dans la clé que le jeu lit réellement.

- **Dossier Jorrit, « Updated Power Usage Data » affiche le texte d'Energy Anomaly** : CIG Issue Council [STARC-176797](https://issue-council.robertsspaceindustries.com/projects/STAR-CITIZEN/issues/STARC-176797). Le contrat `Hockrow_FacilityDelve_P2M4-Stanton4_Repeat` de CIG pointe son paramètre `Description` vers `@Hockrow_FacilityDelve_P2M1_Repeat_desc` au lieu de son propre `P2M4_Repeat_desc`, donc les joueurs voient en jeu le texte d'ambiance Energy Anomaly de P2M1 pour une mission intitulée « Power Usage Data ». Smart Citizen contourne cela en deux temps, tous deux déclarés dans `patches/contracts/contractgenerator/mercenary_guild/hockrowagency/hockrowagency_facilitydelve.patch.json` :
  1. Une modification du XML DataForge pour que notre générateur d'enrichissements attache la bonne liste de plans P2M4 (Corbel Smolder, Geist Rogue/Whiteout) à `P2M4_Repeat_desc` au lieu de la rabattre sur celle de P2M1.
  2. Un contournement de texte qui ajoute le contenu complet de `P2M4_Repeat_desc` (son texte d'ambiance plus sa propre liste de plans) à la suite de `P2M1_Repeat_desc`, séparé par un intercalaire libellé. Comme le jeu lit le pointeur bugué et consulte `P2M1_Repeat_desc` pour les deux contrats, le contrat P2M4 affiche désormais son contenu prévu. Les joueurs de P2M1 voient le bloc P2M4 en annexe libellée après leur propre description : plus verbeux, mais les deux contrats affichent maintenant la bonne liste de plans et le bon texte d'ambiance.

  Quand CIG corrigera STARC-176797, le fichier de correctif pourra être supprimé et la régénération suivante produira de nouveau des descriptions proprement séparées.

## Retours, bugs et vote des fonctionnalités

- **Signalez les bugs, partagez vos configurations et votez pour les prochaines fonctionnalités** dans le canal Discord dédié à Smart Citizen : [Discord Osiris DevWorks, retours et votes #smart-citizen](https://discord.com/channels/1438175448420057323/1472394204347895890) (il faut d'abord rejoindre le serveur Osiris DevWorks : [invitation](https://discord.gg/BNzRegKZ7k)). La priorisation des fonctionnalités est pilotée par les réactions et votes dans ce canal : plus une demande a de soutien, plus vite elle arrive.
- Quand vous signalez un bug, joignez le journal (onglet Journal → **Exporter**) et précisez votre version de Star Citizen, pour que nous puissions distinguer les problèmes d'origine des changements en amont.
