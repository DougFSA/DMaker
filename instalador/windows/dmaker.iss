; Instalador do DMaker para Windows (Inno Setup 6). Quem monta os valores e chama o ISCC é o `dmaker release build`:
;   /DVersao        versão do DMaker (2.0.0)
;   /DPrograma      pasta já montada do programa (Python portátil, bin, assets, licenças, lançadores)
;   /DDados         pasta com o que vai para a pasta de dados (cache\models)
;   /DSaida         onde o instalador e as fatias saem
;   /DNomeBase      nome do instalador sem extensão (DMaker-2.0.0-windows-x64)
;   /DOllama        o OllamaSetup.exe que acompanha o pacote
;   /DOllamaVersao  a versão dele
;   /DFatia         tamanho máximo de cada fatia em bytes (abaixo de 2 GiB, o limite de arquivo do GitHub)
;
; Por usuário (sem administrador). O programa e a pasta dos dados são separados: atualizar nunca mexe nos dados e
; desinstalar só os apaga se a pessoa confirmar.

#ifndef Versao
  #error Rode pelo `dmaker release build`: faltou /DVersao.
#endif

[Setup]
AppId={{8A6DBFA9-7775-4448-95FF-C035EA10DC0C}
AppName=DMaker
AppVersion={#Versao}
AppPublisher=DMaker
DefaultDirName={localappdata}\Programs\DMaker
UsePreviousAppDir=yes
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#Saida}
OutputBaseFilename={#NomeBase}
; Os modelos quase não comprimem e o build tem dezenas de milhares de arquivos: compressão rápida.
Compression=zip/3
SolidCompression=no
DiskSpanning=yes
DiskSliceSize={#Fatia}
SlicesPerDisk=1
WizardStyle=modern
ChangesEnvironment=yes
SetupLogging=yes
UninstallDisplayName=DMaker {#Versao}
InfoBeforeFile={#Programa}\licencas\LICENCAS.txt
InfoAfterFile=depois-da-instalacao.txt

[Languages]
Name: "ptbr"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar um atalho na área de trabalho"; Flags: unchecked
Name: "path"; Description: "Pôr o comando dmaker no PATH do usuário"; Flags: unchecked

[Dirs]
Name: "{code:Dados}"

[InstallDelete]
; Atualizar por cima: o Python do programa é trocado inteiro, para não sobrar módulo da versão anterior.
Type: filesandordirs; Name: "{app}\python"

[Files]
Source: "{#Programa}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
; Os modelos vão para a pasta dos dados, só os que ainda não existem, e a desinstalação nunca os remove sozinha.
Source: "{#Dados}\*"; DestDir: "{code:Dados}"; Flags: recursesubdirs createallsubdirs onlyifdoesntexist uninsneveruninstall
; O Ollama só é extraído (e instalado) se a máquina ainda não tiver o programa.
Source: "{#Ollama}"; DestDir: "{tmp}"; DestName: "OllamaSetup.exe"; Flags: deleteafterinstall; Check: OllamaMissing

[Icons]
Name: "{autoprograms}\DMaker"; Filename: "{app}\dmaker.cmd"; Parameters: "ui"; WorkingDir: "{code:Dados}"; Comment: "Abre a interface do DMaker"
Name: "{autoprograms}\DMaker (pasta dos dados)"; Filename: "{win}\explorer.exe"; Parameters: """{code:Dados}"""
Name: "{autodesktop}\DMaker"; Filename: "{app}\dmaker.cmd"; Parameters: "ui"; WorkingDir: "{code:Dados}"; Tasks: desktopicon

[Registry]
; Lembra a pasta dos dados para a atualização e a desinstalação; sai junto com o desinstalador.
Root: HKCU; Subkey: "Software\DMaker"; ValueType: string; ValueName: "Dados"; ValueData: "{code:Dados}"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Environment"; ValueType: expandsz; ValueName: "Path"; ValueData: "{olddata};{app}"; Tasks: path; Check: NeedsAddPath(ExpandConstant('{app}'))

[Run]
Filename: "{tmp}\OllamaSetup.exe"; Parameters: "/VERYSILENT /NORESTART"; StatusMsg: "Instalando o Ollama {#OllamaVersao} (nenhum modelo é baixado)..."; Flags: waituntilterminated; Check: OllamaMissing

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Code]
var
  DataPage: TInputDirWizardPage;
  UninstallDataDir: String;

function DefaultDataDir: String;
var
  Previous: String;
begin
  Result := ExpandConstant('{param:DADOS|}');
  if Result <> '' then
    Exit;
  if RegQueryStringValue(HKCU, 'Software\DMaker', 'Dados', Previous) and (Previous <> '') then
    Result := Previous
  else
    Result := ExpandConstant('{localappdata}\DMaker');
end;

function Dados(Param: String): String;
begin
  if DataPage <> nil then
    Result := DataPage.Values[0]
  else
    Result := DefaultDataDir;
  while (Length(Result) > 3) and (Result[Length(Result)] = '\') do
    Delete(Result, Length(Result), 1);
end;

procedure InitializeWizard;
begin
  DataPage := CreateInputDirPage(wpSelectDir, 'Pasta dos dados',
    'Onde ficam os seus projetos, vozes, saídas e o cache?',
    'Essa pasta guarda tudo o que é seu e nunca é apagada ao atualizar. Escolha outra pasta se a unidade padrão tiver pouco espaço.',
    False, '');
  DataPage.Add('');
  DataPage.Values[0] := DefaultDataDir;
end;

function OllamaFolderHasProgram: Boolean;
begin
  Result := FileExists(ExpandConstant('{localappdata}\Programs\Ollama\ollama.exe'))
    or (FileSearch('ollama.exe', GetEnv('PATH')) <> '');
end;

function OllamaMissing: Boolean;
begin
  Result := not OllamaFolderHasProgram;
  if not Result then
    Log('Ollama ja instalado nesta maquina: passo do Ollama pulado.');
end;

function NeedsAddPath(Param: String): Boolean;
var
  Current: String;
begin
  if not RegQueryStringValue(HKCU, 'Environment', 'Path', Current) then
    Current := '';
  Result := Pos(';' + Uppercase(Param) + ';', ';' + Uppercase(Current) + ';') = 0;
end;

procedure WriteMarker;
var
  Raw: AnsiString;
  Json, DataPath: String;
  Lines: TArrayOfString;
begin
  if not LoadStringFromFile(ExpandConstant('{app}\instalacao.json.modelo'), Raw) then
    RaiseException('instalacao.json.modelo nao encontrado em ' + ExpandConstant('{app}'));
  Json := String(Raw);
  DataPath := Dados('');
  StringChangeEx(DataPath, '\', '\\', True);
  StringChangeEx(Json, '@@DADOS@@', DataPath, True);
  SetArrayLength(Lines, 1);
  Lines[0] := Json;
  SaveStringsToUTF8File(ExpandConstant('{app}\instalacao.json'), Lines, False);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    WriteMarker;
end;

procedure RemoveFromUserPath(Folder: String);
var
  Current, Wrapped: String;
begin
  if not RegQueryStringValue(HKCU, 'Environment', 'Path', Current) then
    Exit;
  Wrapped := ';' + Current + ';';
  if StringChangeEx(Wrapped, ';' + Folder + ';', ';', True) > 0 then
  begin
    Current := Copy(Wrapped, 2, Length(Wrapped) - 2);
    RegWriteExpandStringValue(HKCU, 'Environment', 'Path', Current);
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
  begin
    if not RegQueryStringValue(HKCU, 'Software\DMaker', 'Dados', UninstallDataDir) then
      UninstallDataDir := '';
    RemoveFromUserPath(ExpandConstant('{app}'));
  end;
  if (CurUninstallStep = usPostUninstall) and (UninstallDataDir <> '') and DirExists(UninstallDataDir)
    and (not UninstallSilent) then
  begin
    if MsgBox('Apagar também os seus dados (projetos, vozes, saídas, cache e modelos) em' + #13#10 + UninstallDataDir + '?' + #13#10#13#10 + 'Isso não pode ser desfeito.',
      mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
      DelTree(UninstallDataDir, True, True, True);
  end;
end;
