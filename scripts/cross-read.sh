#!/usr/bin/env bash
# Read a synthesized bundle with an implementation that shares no code with
# the writer: AssetsTools.NET (C#, MIT). unityz both creates the bundle and
# re-reads it before the file lands, so this is the independent second reader
# for a construction claim; the fresh-client acceptance remains the real gate.
set -euo pipefail

ASSETSTOOLS_VERSION="3.0.5"

usage() {
	cat <<'HELP'
Read a bundle with AssetsTools.NET and print what it sees as one JSON object.

USAGE
  scripts/cross-read.sh <bundle.unity3d>

OUTPUT
  {"node": "CAB-...", "revision": "2022.3.62f2", "platform": 19,
   "typeTree": true, "objects": [{"pathId", "classId", "name"}, ...],
   "container": ["stem", ...]}

Needs the .NET SDK (`dotnet`) and, the first time, network access for the
pinned AssetsTools.NET package. The reader project is generated under
${XDG_CACHE_HOME:-~/.cache}/shamway/cross-read and reused afterwards.
HELP
}

if [[ $# -ne 1 || "$1" == "-h" || "$1" == "--help" ]]; then
	usage >&2
	exit 2
fi
bundle="$1"
if [[ ! -f "$bundle" ]]; then
	echo "ERROR: no bundle at $bundle" >&2
	exit 1
fi
if ! command -v dotnet >/dev/null 2>&1; then
	echo "ERROR: cross-read needs the .NET SDK (dotnet) on PATH" >&2
	exit 1
fi

project="${XDG_CACHE_HOME:-$HOME/.cache}/shamway/cross-read/assetstools-$ASSETSTOOLS_VERSION"
mkdir -p "$project"
cat >"$project/CrossRead.csproj" <<EOP
<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <OutputType>Exe</OutputType>
    <TargetFramework>net10.0</TargetFramework>
    <RollForward>Major</RollForward>
    <Nullable>enable</Nullable>
    <ImplicitUsings>enable</ImplicitUsings>
  </PropertyGroup>
  <ItemGroup>
    <PackageReference Include="AssetsTools.NET" Version="$ASSETSTOOLS_VERSION" />
  </ItemGroup>
</Project>
EOP
cat >"$project/Program.cs" <<'EOP'
using System.Text.Json;
using AssetsTools.NET;
using AssetsTools.NET.Extra;

var am = new AssetsManager();
var bundle = am.LoadBundleFile(args[0], true);
var assets = am.LoadAssetsFileFromBundle(bundle, 0, false);
var file = assets.file;
var objects = new List<object>();
var container = new List<string>();
foreach (var info in file.AssetInfos)
{
    var root = am.GetBaseField(assets, info);
    var name = root["m_Name"].IsDummy ? "" : root["m_Name"].AsString;
    objects.Add(new { pathId = info.PathId, classId = info.TypeId, name });
    if (info.TypeId == 142)
        foreach (var entry in root["m_Container.Array"]) container.Add(entry["first"].AsString);
}
Console.WriteLine(JsonSerializer.Serialize(new
{
    node = bundle.file.BlockAndDirInfo.DirectoryInfos[0].Name,
    revision = file.Metadata.UnityVersion,
    platform = (int)file.Metadata.TargetPlatform,
    typeTree = file.Metadata.TypeTreeEnabled,
    objects,
    container,
}));
EOP

bundle_abs="$(cd "$(dirname "$bundle")" && pwd)/$(basename "$bundle")"
# Build first with its output on stderr, so stdout carries exactly one JSON line.
if ! dotnet build "$project" -c Release --nologo -v quiet -clp:NoSummary >&2; then
	echo "ERROR: could not build the AssetsTools.NET reader under $project" >&2
	exit 1
fi
if ! dotnet run --project "$project" -c Release --no-build -- "$bundle_abs"; then
	echo "ERROR: AssetsTools.NET could not read $bundle" >&2
	exit 1
fi
