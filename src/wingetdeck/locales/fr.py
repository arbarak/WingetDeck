"""French, keyed by the English text. Placeholders in {braces} must stay as they are.

Write a plain space before : ? ! and ; as usual. It becomes a no-break space below, so the sign never starts a
line on its own. Use straight apostrophes: every console font has them.
"""

from __future__ import annotations

import re

_FR = {
    # Run controls and outcomes
    "Stopped during download": "Arrêté pendant le téléchargement",
    "Force stopped during install. This app may need reinstalling.":
        "Arrêt forcé pendant l'installation. Cette application devra peut-être être réinstallée.",
    "Pausing after this install…": "Pause après cette installation…",
    "Pausing after this package…": "Pause après ce paquet…",
    "Pause after this install": "Pause après l'installation",
    "Pause after this package": "Pause après ce paquet",
    "Stop after this one": "Arrêter après celui-ci",
    "Stop now": "Arrêter maintenant",
    "Force stop": "Forcer l'arrêt",
    "Pause": "Pause",
    "Resume": "Reprendre",
    "Stop": "Arrêter",
    "Upgraded": "Mis à jour",
    "This package has licence agreements. Turn on accepting agreements in Settings to upgrade it.":
        "Ce paquet a des contrats de licence. Activez l'acceptation des contrats dans les Paramètres pour le mettre à jour.",
    "Could not save the queue: {error}": "Impossible d'enregistrer la file : {error}",
    "The run stopped unexpectedly: {error}": "L'exécution s'est arrêtée de façon inattendue : {error}",
    "Upgrading {name}": "Mise à jour de {name}",
    "{name}: the download failed after the pause, trying once more":
        "{name} : le téléchargement a échoué après la pause, nouvel essai",
    "Could not start winget: {error}": "Impossible de démarrer winget : {error}",
    "Lost contact with winget: {error}": "Contact perdu avec winget : {error}",
    "Windows would not let this app stop the installer, because it is running as administrator. "
    "It will carry on until it finishes.":
        "Windows n'a pas laissé cette application arrêter l'installateur, car il s'exécute en administrateur. "
        "Il continuera jusqu'à la fin.",
    "A restore point needs administrator rights.": "Un point de restauration demande les droits d'administrateur.",
    "Could not create a restore point: {reason}": "Impossible de créer un point de restauration : {reason}",
    # The app
    "WingetDeck — Package Upgrader": "WingetDeck — Mise à jour des paquets",
    "Logs": "Journaux",
    "Settings": "Paramètres",
    "History": "Historique",
    "Licence agreements": "Contrats de licence",
    "Many packages come with licence agreements, and winget's sources have terms of their own. Winget stops and "
    "asks about these, but an upgrade running here cannot answer it.\n\nTo go on without being asked, WingetDeck can "
    "add --accept-package-agreements and --accept-source-agreements to each upgrade, which accepts them on your "
    "behalf. You can read a package's licence on its homepage from the details panel.\n\nWithout this, packages "
    "that need it are marked as skipped. You can change it in Settings.":
        "Beaucoup de paquets ont des contrats de licence, et les sources de winget ont leurs propres conditions. "
        "Winget s'arrête pour les demander, mais une mise à jour lancée ici ne peut pas répondre.\n\n"
        "Pour continuer sans question, WingetDeck peut ajouter --accept-package-agreements et "
        "--accept-source-agreements à chaque mise à jour, ce qui les accepte en votre nom. Vous pouvez lire la "
        "licence d'un paquet sur sa page d'accueil, depuis le panneau de détails.\n\n"
        "Sans cela, les paquets concernés sont marqués comme sautés. Vous pourrez changer ce choix dans les Paramètres.",
    "Accept agreements": "Accepter les contrats",
    "Skip those packages": "Sauter ces paquets",
    "Go on without it": "Continuer sans",
    "Saving the list of installed apps before starting…":
        "Enregistrement de la liste des applications installées avant de commencer…",
    "Could not save the list of installed apps": "Impossible d'enregistrer la liste des applications installées",
    "Before each run a list of installed versions is saved, so there is a record of how things were. "
    "This time it failed: {error}\n\nGo on without it?":
        "Avant chaque exécution, la liste des versions installées est enregistrée, pour garder une trace de l'état "
        "d'avant. Cette fois, cela a échoué : {error}\n\nContinuer sans ?",
    "The last run did not finish: {names}.\n\nAn interrupted download starts again from the beginning.":
        "La dernière exécution n'est pas allée au bout : {names}.\n\nUn téléchargement interrompu reprend depuis le début.",
    "Resume unfinished queue ({count} left)?": "Reprendre la file inachevée ({count} restant(s)) ?",
    "Don't resume": "Ne pas reprendre",
    "Ask me later": "Me demander plus tard",
    "A run is going": "Une exécution est en cours",
    "Quit after this package": "Quitter après ce paquet",
    "Quit now": "Quitter maintenant",
    "Keep running": "Continuer",
    "Your queue is saved, and WingetDeck offers to continue it next time.":
        "Votre file est enregistrée, et WingetDeck proposera de la reprendre la prochaine fois.",
    "This package may be installing. Quitting now ends winget along with this app. An installer that has already "
    "started may carry on by itself, but the package could be left half-installed.":
        "Ce paquet est peut-être en cours d'installation. Quitter maintenant arrête winget avec cette application. "
        "Un installateur déjà lancé peut continuer seul, mais le paquet risque de rester à moitié installé.",
    "A download is running. Quitting now stops winget, which can leave a partial file in its temp folder. "
    "Nothing has been installed for this package yet.":
        "Un téléchargement est en cours. Quitter maintenant arrête winget, ce qui peut laisser un fichier partiel "
        "dans son dossier temporaire. Rien n'a encore été installé pour ce paquet.",
    "Nothing to do": "Rien à faire",
    "Window too small.\nMake it bigger: any running upgrade continues.":
        "Fenêtre trop petite.\nAgrandissez-la : une mise à jour en cours continue.",
    # Details
    "Publisher: {value}": "Éditeur : {value}",
    "Homepage: {value}": "Page d'accueil : {value}",
    "Release notes:": "Notes de version :",
    "Asking winget…": "Question à winget…",
    "Ignore": "Ignorer",
    "Options": "Options",
    "Close": "Fermer",
    "Unpin": "Désépingler",
    "Pin": "Épingler",
    "Could not ask winget: {error}": "Impossible d'interroger winget : {error}",
    "Could not change the pin: {error}": "Impossible de changer l'épinglage : {error}",
    # History
    "Roll back?": "Revenir en arrière ?",
    "Roll back": "Revenir en arrière",
    "Roll back to the earlier version": "Revenir à la version précédente",
    "See log": "Voir le journal",
    "No upgrades have been recorded yet.": "Aucune mise à jour n'a encore été enregistrée.",
    "Roll back is not available during an upgrade run.":
        "Le retour en arrière n'est pas disponible pendant une mise à jour.",
    "Asking winget which versions of {name} it still has…": "Recherche des versions de {name} encore proposées par winget…",
    "Could not ask winget for versions of {name}: {error}": "Impossible d'obtenir les versions de {name} : {error}",
    "the earlier version": "la version précédente",
    "{name} cannot be rolled back: {earlier} is no longer available from its source.":
        "Impossible de revenir en arrière pour {name} : {earlier} n'est plus disponible dans sa source.",
    "This installs {name} {target} over {current}. Some apps do not support going backwards, and winget may offer "
    "the newer version again next time.":
        "Cela installe {name} {target} à la place de {current}. Certaines applications ne supportent pas le retour "
        "en arrière, et winget pourra reproposer la version récente la prochaine fois.",
    # Logs
    "see details": "voir les détails",
    "Could not open {folder}: {error}": "Impossible d'ouvrir {folder} : {error}",
    "The report is saved on this PC only. Your Windows user name, custom installer arguments, --header values and "
    "proxy passwords are removed.\n\nIt will contain:\n  {contents}":
        "Le rapport est enregistré sur ce PC uniquement. Votre nom d'utilisateur Windows, les arguments "
        "d'installateur personnalisés, les valeurs --header et les mots de passe de proxy sont retirés.\n\n"
        "Il contiendra :\n  {contents}",
    "Save a diagnostic report?": "Enregistrer un rapport de diagnostic ?",
    "Could not save the report: {error}": "Impossible d'enregistrer le rapport : {error}",
    "Saved: {path}": "Enregistré : {path}",
    "Save report": "Enregistrer le rapport",
    "winget output for {id}": "Sortie de winget pour {id}",
    "There is no winget output for this package in this session.":
        "Aucune sortie de winget pour ce paquet dans cette session.",
    "Could not read it: {error}": "Lecture impossible : {error}",
    "ALL": "TOUT",
    "All packages": "Tous les paquets",
    "Open logs folder": "Ouvrir le dossier",
    "Save diagnostic report": "Enregistrer un rapport",
    # Getting winget
    "Cancelling…": "Annulation…",
    'Install "App Installer" from the Store page, then press Check again.':
        'Installez "App Installer" depuis la page du Store, puis appuyez sur Vérifier à nouveau.',
    "Looking for a version of winget made for this PC…": "Recherche d'une version de winget faite pour ce PC…",
    "Install winget {version}?": "Installer winget {version} ?",
    "Activate winget?": "Activer winget ?",
    "Asking Windows to activate winget…": "Demande d'activation de winget à Windows…",
    "WingetDeck upgrades apps through winget, which could not be used here.\n\n"
    "Get winget can sort this out, and it asks before each step:\n"
    "  1. It tries to activate a winget that is already on this PC.\n"
    "  2. If that is not enough, it finds the newest version made for this\n"
    "     PC, then offers to download and install it from Microsoft's releases.\n\n"
    'Or install "App Installer" from the Microsoft Store, then press Check again.\n'
    "Winget needs Windows 10 1809 or newer, and cannot run on Server Core.":
        "WingetDeck met à jour les applications avec winget, qui n'a pas pu être utilisé ici.\n\n"
        "Obtenir winget peut régler cela, en demandant avant chaque étape :\n"
        "  1. Il essaie d'activer un winget déjà présent sur ce PC.\n"
        "  2. Si cela ne suffit pas, il trouve la version la plus récente faite\n"
        "     pour ce PC, puis propose de la télécharger et de l'installer depuis\n"
        "     les publications de Microsoft.\n\n"
        'Ou installez "App Installer" depuis le Microsoft Store, puis appuyez sur Vérifier à nouveau.\n'
        "Winget demande Windows 10 1809 ou plus récent, et ne fonctionne pas sur Server Core.",
    "Activate winget": "Activer winget",
    "Windows can have winget on a PC without having set it up for your account yet. WingetDeck can ask Windows to "
    "do that now.\n\nNothing is downloaded, and no admin rights are needed.":
        "Windows peut avoir winget sur un PC sans l'avoir encore préparé pour votre compte. WingetDeck peut demander "
        "à Windows de le faire maintenant.\n\nRien n'est téléchargé, et aucun droit d'administrateur n'est nécessaire.",
    "Download and install": "Télécharger et installer",
    "App Installer {version} is on this PC, but its winget command is switched off. Open Windows Settings, then "
    "Apps, then Advanced app settings (on Windows 10, Apps & features), then App execution aliases. Turn on winget, "
    "then press Check again.":
        "App Installer {version} est sur ce PC, mais sa commande winget est désactivée. Ouvrez les Paramètres de "
        "Windows, puis Applications, puis Paramètres avancés des applications (sur Windows 10, Applications et "
        "fonctionnalités), puis Alias d'exécution d'application. Activez winget, puis appuyez sur Vérifier à nouveau.",
    "No version of winget was found for this PC (Windows build {build}, {architecture}). Try the Microsoft Store.":
        "Aucune version de winget n'a été trouvée pour ce PC (Windows build {build}, {architecture}). "
        "Essayez le Microsoft Store.",
    "Winget was installed, but this PC is not showing it yet. Press Check again, or sign out of Windows and back in.":
        "Winget a été installé, mais ce PC ne le montre pas encore. Appuyez sur Vérifier à nouveau, ou fermez puis "
        "rouvrez votre session Windows.",
    "Cancelled. Nothing was installed.": "Annulé. Rien n'a été installé.",
    "This version is made for this PC: Windows build {build}, {architecture} processor.\n\nWingetDeck will download "
    "{size} MB from Microsoft's official releases on GitHub, check the checksum and Microsoft's signature, then "
    "install it for your Windows account. No admin rights are needed.\n\nIt needs about {space} MB free while it "
    "works. The downloaded files are removed afterwards.":
        "Cette version est faite pour ce PC : Windows build {build}, processeur {architecture}.\n\n"
        "WingetDeck va télécharger {size} Mo depuis les publications officielles de Microsoft sur GitHub, vérifier "
        "la somme de contrôle et la signature de Microsoft, puis l'installer pour votre compte Windows. Aucun droit "
        "d'administrateur n'est nécessaire.\n\nIl faut environ {space} Mo libres pendant l'opération. Les fichiers "
        "téléchargés sont supprimés ensuite.",
    "What happened: {reason}": "Ce qui s'est passé : {reason}",
    "Get winget": "Obtenir winget",
    "Cancel": "Annuler",
    "Check again": "Vérifier à nouveau",
    "The download tried to go to an address outside GitHub: {host}":
        "Le téléchargement a tenté d'aller vers une adresse hors de GitHub : {host}",
    "Refused to open an address outside GitHub: {host}": "Ouverture refusée d'une adresse hors de GitHub : {host}",
    "Windows did not finish within {seconds} seconds.": "Windows n'a pas terminé en {seconds} secondes.",
    "Windows PowerShell could not start: {error}": "Windows PowerShell n'a pas pu démarrer : {error}",
    "Windows reported an error ({code}).": "Windows a signalé une erreur ({code}).",
    "The Microsoft Store could not be opened on this PC.": "Le Microsoft Store n'a pas pu être ouvert sur ce PC.",
    "GitHub did not allow reading part of the file, so it could not be checked first.":
        "GitHub n'a pas permis de lire une partie du fichier, il n'a donc pas pu être vérifié d'abord.",
    "Could not tell what kind of processor this PC has.": "Impossible de savoir quel processeur a ce PC.",
    "Could not reach GitHub to look for winget: {error}": "Impossible de joindre GitHub pour chercher winget : {error}",
    "GitHub sent an answer that could not be read.": "GitHub a envoyé une réponse illisible.",
    "Could not reach GitHub to check winget: {error}": "Impossible de joindre GitHub pour vérifier winget : {error}",
    "Installing winget needs about {need} MB free on this drive, and only {free} MB is free.":
        "Installer winget demande environ {need} Mo libres sur ce disque, et seulement {free} Mo sont libres.",
    "Could not use the temporary folder: {error}": "Impossible d'utiliser le dossier temporaire : {error}",
    "Checking Microsoft's signature…": "Vérification de la signature de Microsoft…",
    "Installing winget. This can take a few minutes…": "Installation de winget. Cela peut prendre quelques minutes…",
    "Downloading winget: {percent}% of {size} MB": "Téléchargement de winget : {percent} % de {size} Mo",
    "The download stopped: {error}": "Le téléchargement s'est arrêté : {error}",
    "{file} does not match the checksum GitHub lists, so it was not installed.":
        "{file} ne correspond pas à la somme de contrôle indiquée par GitHub, il n'a donc pas été installé.",
    "{file} has no valid Microsoft signature, so it was not installed.":
        "{file} n'a pas de signature Microsoft valide, il n'a donc pas été installé.",
    "The downloaded package could not be read, so it was not installed.":
        "Le paquet téléchargé est illisible, il n'a donc pas été installé.",
    "The downloaded package is not winget, so it was not installed.":
        "Le paquet téléchargé n'est pas winget, il n'a donc pas été installé.",
    "The downloaded parts winget needs could not be unpacked.":
        "Les éléments téléchargés dont winget a besoin n'ont pas pu être décompressés.",
    "This release has none of the parts winget needs on an {architecture} PC.":
        "Cette publication ne contient aucun des éléments dont winget a besoin sur un PC {architecture}.",
    # Options for one package
    "Options for {name}": "Options pour {name}",
    "Use the defaults": "Utiliser les valeurs par défaut",
    # Packages
    "Updating sources…": "Mise à jour des sources…",
    "sources updated": "sources à jour",
    "Could not update sources, the list may be out of date: {error}":
        "Impossible de mettre à jour les sources, la liste n'est peut-être pas à jour : {error}",
    "Checking for upgrades…": "Recherche des mises à jour…",
    "Could not check for upgrades: {error}": "Impossible de rechercher les mises à jour : {error}",
    "Winget's source agreements are not accepted. You can change this in Settings.":
        "Les contrats des sources de winget ne sont pas acceptés. Vous pouvez changer cela dans les Paramètres.",
    "{count} upgrade(s) available": "{count} mise(s) à jour disponible(s)",
    "{count} new since the last check": "{count} nouvelle(s) depuis la dernière recherche",
    "{count} no longer need upgrading": "{count} n'ont plus besoin de mise à jour",
    "{count} ignored package(s) hidden": "{count} paquet(s) ignoré(s) masqué(s)",
    "{count} package(s) with an unknown version hidden by winget":
        "{count} paquet(s) de version inconnue masqué(s) par winget",
    "Everything is up to date. Press Refresh to check again.":
        "Tout est à jour. Appuyez sur Actualiser pour vérifier de nouveau.",
    "Not available during an upgrade. It comes back when the run ends or pauses between packages.":
        "Indisponible pendant une mise à jour. Revient quand l'exécution se termine ou fait une pause entre deux paquets.",
    "Update winget's sources, then check again": "Mettre à jour les sources de winget, puis vérifier de nouveau",
    "Winget will not look for upgrades until its source agreements are accepted.":
        "Winget ne cherchera pas de mises à jour tant que les contrats de ses sources ne sont pas acceptés.",
    "Filter": "Filtrer",
    "Upgrade": "Mettre à jour",
    "Details": "Détails",
    "Type to filter, Esc to clear": "Tapez pour filtrer, Échap pour effacer",
    "Refresh": "Actualiser",
    "All": "Tout",
    "None": "Aucun",
    "Major": "Majeures",
    "Minor": "Mineures",
    "Patch": "Correctifs",
    "To run": "En cours",
    "UPGRADE": "METTRE À JOUR",
    # The run
    "new run": "nouvelle exécution",
    "FINISHED": "TERMINÉ",
    "PAUSED": "EN PAUSE",
    "STARTING": "DÉMARRAGE",
    "All done": "Tout est fait",
    "Waiting": "En attente",
    "Paused": "En pause",
    "Finished": "Terminé",
    "{count} upgraded": "{count} mis à jour",
    "{count} needs a restart": "{count} demande un redémarrage",
    "{count} need a restart": "{count} demandent un redémarrage",
    "{count} skipped": "{count} sauté(s)",
    "{count} failed": "{count} en échec",
    "{count} stopped": "{count} arrêté(s)",
    "Finished: {parts}": "Terminé : {parts}",
    "{name} is in use. Close it yourself, then press Retry failed. ({code})":
        "{name} est en cours d'utilisation. Fermez-le vous-même, puis appuyez sur Relancer les échecs. ({code})",
    "No output from winget for a while. It may just be slow, so nothing was stopped.":
        "Winget n'affiche plus rien depuis un moment. Il est peut-être juste lent, donc rien n'a été arrêté.",
    "Turn it on": "L'activer",
    "DOWNLOADING": "TÉLÉCHARGEMENT",
    "VERIFYING": "VÉRIFICATION",
    "INSTALLING": "INSTALLATION",
    "WORKING": "EN COURS",
    "Pause during a download": "Pause pendant un téléchargement",
    "Not now": "Pas maintenant",
    "The winget setting could not be changed: {error}": "Le réglage de winget n'a pas pu être modifié : {error}",
    "The direct downloader is on from the next package. Settings has an Undo.":
        "Le téléchargement direct est actif à partir du prochain paquet. Les Paramètres permettent d'annuler.",
    "Stop the upgrade run?": "Arrêter la mise à jour ?",
    "The packages still waiting will not be upgraded.": "Les paquets encore en attente ne seront pas mis à jour.",
    "Stop after this one lets the current package finish, then stops the rest.":
        "Arrêter après celui-ci laisse finir le paquet en cours, puis arrête le reste.",
    "An installer is running. Force stop ends it midway, which is only for an installer that has hung. "
    "You will be asked once more.":
        "Un installateur est en cours. Forcer l'arrêt l'interrompt en plein milieu, ce qui n'est à faire que pour un "
        "installateur bloqué. Une confirmation vous sera encore demandée.",
    "Stop now ends the download and nothing will install. A partial file may be left in winget's temporary folder.":
        "Arrêter maintenant interrompt le téléchargement et rien ne sera installé. Un fichier partiel peut rester "
        "dans le dossier temporaire de winget.",
    "Stop now ends winget and nothing will install, but Windows' download service may finish the download in the "
    "background, and that file may stay in winget's temporary folder.":
        "Arrêter maintenant interrompt winget et rien ne sera installé, mais le service de téléchargement de Windows "
        "peut finir le téléchargement en arrière-plan, et ce fichier peut rester dans le dossier temporaire de winget.",
    "Stopping after this package.": "Arrêt après ce paquet.",
    "Not stopped: an installer has started, and ending one midway can break the app.":
        "Pas arrêté : un installateur a démarré, et l'interrompre en plein milieu peut casser l'application.",
    "Stopped. Windows' download service may still finish the download in the background.":
        "Arrêté. Le service de téléchargement de Windows peut encore finir le téléchargement en arrière-plan.",
    "This download cannot be held right now. Windows' download service carries it on even if winget is frozen, so a "
    "true Pause needs winget's direct downloader.\n\nTurning it on changes one winget setting (network.downloader) "
    "for all winget use on this PC, not only here. Delivery Optimization will not be used, so large downloads may be "
    "slower. Your settings file is backed up first, and Settings has an Undo.\n\nIt applies from the next package. "
    "This one will pause when it has finished.":
        "Ce téléchargement ne peut pas être suspendu pour l'instant. Le service de téléchargement de Windows le "
        "poursuit même si winget est figé, donc une vraie Pause demande le téléchargement direct de winget.\n\n"
        "L'activer change un réglage de winget (network.downloader) pour tout usage de winget sur ce PC, pas "
        "seulement ici. L'Optimisation de la distribution ne sera plus utilisée, donc les gros téléchargements "
        "peuvent être plus lents. Votre fichier de réglages est d'abord sauvegardé, et les Paramètres permettent "
        "d'annuler.\n\nCela s'applique à partir du prochain paquet. Celui-ci se mettra en pause une fois terminé.",
    "Force stop this installer?": "Forcer l'arrêt de cet installateur ?",
    "Ending an installer midway can leave the app broken until it is reinstalled. Use this only if the installer "
    "has hung.":
        "Interrompre un installateur en plein milieu peut laisser l'application cassée jusqu'à sa réinstallation. "
        "À n'utiliser que si l'installateur est bloqué.",
    "Keep going": "Continuer",
    "Pause/Resume": "Pause/Reprise",
    "Packages": "Paquets",
    "Retry failed": "Relancer les échecs",
    "download": "débit",
    "received": "reçu",
    "LOG": "JOURNAL",
    "QUEUE": "FILE",
    # Settings
    "Automatic ({language})": "Automatique ({language})",
    "Language changed. It is saved already: the rest of this page still needs Save.":
        "Langue changée. Elle est déjà enregistrée : le reste de cette page demande encore Enregistrer.",
    "Not available during an upgrade run.": "Indisponible pendant une mise à jour.",
    "Winget's settings are locked by your organisation, so this cannot be changed.":
        "Les réglages de winget sont verrouillés par votre organisation, cela ne peut donc pas être changé.",
    "It is on. Pause can hold a download, and Delivery Optimization is not used for any winget download.":
        "Il est actif. La Pause peut suspendre un téléchargement, et l'Optimisation de la distribution n'est "
        "utilisée pour aucun téléchargement de winget.",
    "It is off. Pause waits until the current package has finished.":
        "Il est désactivé. La Pause attend la fin du paquet en cours.",
    "Logs use {size} MB in {folder}. Nothing is deleted automatically.":
        "Les journaux occupent {size} Mo dans {folder}. Rien n'est supprimé automatiquement.",
    "Logs have grown large: {size} MB in {folder}. Clean up below if you wish.":
        "Les journaux sont devenus volumineux : {size} Mo dans {folder}. Faites le ménage ci-dessous si vous le souhaitez.",
    "Please enter a whole number of minutes, above zero.": "Entrez un nombre entier de minutes, supérieur à zéro.",
    "Saved.": "Enregistré.",
    "Windows did not restart the app as administrator, so this copy stays open.":
        "Windows n'a pas relancé l'application en administrateur, cette copie reste donc ouverte.",
    "Could not restore winget's settings: {error}": "Impossible de restaurer les réglages de winget : {error}",
    "Winget's settings are back as they were.": "Les réglages de winget sont revenus comme avant.",
    "This deletes {count} old log file(s) from earlier sessions and cannot be undone. This session's logs stay.":
        "Cela supprime {count} ancien(s) fichier(s) journal des sessions précédentes, sans retour possible. "
        "Les journaux de cette session restent.",
    "Clean up old logs?": "Supprimer les anciens journaux ?",
    "Delete old logs": "Supprimer les anciens journaux",
    "Back": "Retour",
    "This app": "Cette application",
    "Language": "Langue",
    "Theme": "Thème",
    "Warn after no output (minutes)": "Alerter sans sortie après (minutes)",
    "Check for upgrades every (minutes, empty is off)": "Rechercher les mises à jour toutes les (minutes, vide = jamais)",
    "Accept package and source agreements automatically": "Accepter automatiquement les contrats des paquets et des sources",
    "Create a restore point before a run (administrator only)":
        "Créer un point de restauration avant une exécution (administrateur uniquement)",
    "Upgrade options for every package": "Options de mise à jour pour tous les paquets",
    "Winget's direct downloader": "Téléchargement direct de winget",
    "Undo the direct downloader change": "Annuler le changement du téléchargement direct",
    "Administrator": "Administrateur",
    "Without administrator rights each installer may ask for permission itself. An administrator copy uses your "
    "profile folder for its data, not the folder beside the exe.":
        "Sans droits d'administrateur, chaque installateur peut demander l'autorisation lui-même. Une copie lancée en "
        "administrateur range ses données dans votre dossier de profil, pas dans le dossier à côté de l'exe.",
    "Restart as administrator": "Relancer en administrateur",
    "Ignored packages": "Paquets ignorés",
    "Show ignored packages again": "Réafficher les paquets ignorés",
    "Clean up old logs…": "Supprimer les anciens journaux…",
    "Save": "Enregistrer",
    # Start screen
    "This PC has winget {version}. WingetDeck needs {needed} or newer.":
        "Ce PC a winget {version}. WingetDeck demande {needed} ou plus récent.",
    "Could not list winget sources: {error}": "Impossible de lister les sources de winget : {error}",
    "All sources": "Toutes les sources",
    "Microsoft Store only": "Microsoft Store uniquement",
    "{name} only": "{name} uniquement",
    "Start": "Démarrer",
    "Quit": "Quitter",
    "Select a source and press START": "Choisissez une source et appuyez sur DÉMARRER",
    "START": "DÉMARRER",
    "Looking for winget…": "Recherche de winget…",
    "Data folder: {folder}": "Dossier des données : {folder}",
    # Progress parts
    "Download": "Téléchargement",
    "Verify hash": "Vérification",
    "Install": "Installation",
    "Done": "Terminé",
    "Working…": "En cours…",
    "Working": "En cours",
    # Options
    "Silent": "Silencieux",
    "Interactive": "Interactif",
    "Installer's default": "Selon l'installateur",
    "Current user": "Utilisateur actuel",
    "Whole machine": "Toute la machine",
    "Default": "Par défaut",
    "Installer window": "Fenêtre de l'installateur",
    "Scope": "Portée",
    "Architecture": "Architecture",
    "Force, even if the hash or checks fail": "Forcer, même si le hachage ou les contrôles échouent",
    "Uninstall the previous version first": "Désinstaller d'abord la version précédente",
    "Skip dependencies": "Ignorer les dépendances",
    "Include pinned packages": "Inclure les paquets épinglés",
    "Include packages with an unknown version": "Inclure les paquets de version inconnue",
    "Custom arguments": "Arguments ajoutés",
    "Added to the installer's arguments": "Ajoutés aux arguments de l'installateur",
    "Override arguments": "Arguments de remplacement",
    "Replaces the installer's arguments": "Remplacent les arguments de l'installateur",
    # The table
    "major": "majeure",
    "minor": "mineure",
    "patch": "correctif",
    "unknown": "inconnue",
    "Tick": "Cocher",
    "pinned": "épinglé",
    "explicit": "explicite",
    "id cut off": "id tronqué",
    "NEW": "NOUVEAU",
    "NAME": "NOM",
    "INSTALLED": "INSTALLÉE",
    "AVAILABLE": "DISPONIBLE",
    "VERSION": "VERSION",
    "SOURCE": "SOURCE",
    "CHANGE": "TYPE",
    # The queue
    "restart needed": "redémarrage requis",
    "done": "fait",
    "done, restart needed": "fait, redémarrage requis",
    "skipped": "sauté",
    "failed": "échec",
    "stopped": "arrêté",
}

FR: dict[str, str] = {key: re.sub(r" ([:?!;])", " \\1", value) for key, value in _FR.items()}
