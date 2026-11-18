// Syntra 星樞 真正獨立自解壓安裝程式 (Self-Extracting Standalone Installer)
// 內嵌乾淨核心 ZIP 資源，使用者下載後在任何路徑雙擊即可解壓並安裝，無需預先存在專案目錄！
using System;
using System.Diagnostics;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Text;

[assembly: AssemblyTitle("Syntra 星樞 Windows 獨立安裝程式")]
[assembly: AssemblyProduct("Syntra Agent")]
[assembly: AssemblyVersion("2.5.0.0")]

internal static class StandaloneInstaller
{
    private static int Main(string[] args)
    {
        try { Console.OutputEncoding = Encoding.UTF8; } catch { }
        Console.Title = "Syntra 星樞 Windows 獨立安裝程式 (Pure Core)";
        Console.ForegroundColor = ConsoleColor.Cyan;
        Console.WriteLine("==================================================");
        Console.WriteLine("   Syntra Agent v2.5.0 繁體中文純淨安裝引導");
        Console.WriteLine("==================================================");
        Console.ResetColor();

        // 預設安裝目標：使用者本機目錄 %LOCALAPPDATA%\Syntra
        string targetDir = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Syntra");
        Console.WriteLine("\n[1/3] 正在準備解壓核心模組...");
        Console.WriteLine("  安裝目標路徑: " + targetDir);

        try
        {
            if (!Directory.Exists(targetDir))
            {
                Directory.CreateDirectory(targetDir);
            }

            // 從內嵌資源提取 payload.zip
            Assembly asm = Assembly.GetExecutingAssembly();
            string resourceName = "Syntra.payload.zip";
            using (Stream s = asm.GetManifestResourceStream(resourceName))
            {
                if (s == null)
                {
                    // 若無內嵌資源名稱，搜尋所有 stream
                    string[] names = asm.GetManifestResourceNames();
                    foreach (string n in names)
                    {
                        if (n.EndsWith(".zip", StringComparison.OrdinalIgnoreCase))
                        {
                            resourceName = n;
                            break;
                        }
                    }
                }

                using (Stream stream = asm.GetManifestResourceStream(resourceName))
                {
                    if (stream == null)
                    {
                        Console.ForegroundColor = ConsoleColor.Red;
                        Console.WriteLine("✘ 嚴重錯誤：找不到內嵌核心套件資源。");
                        Console.ResetColor();
                        PauseOnExit();
                        return 1;
                    }

                    string tempZip = Path.Combine(Path.GetTempPath(), "Syntra_payload_" + Guid.NewGuid().ToString("N") + ".zip");
                    using (FileStream fs = new FileStream(tempZip, FileMode.Create, FileAccess.Write))
                    {
                        stream.CopyTo(fs);
                    }

                    Console.WriteLine("[2/3] 正在解壓縮檔案至目標目錄...");
                    ZipFile.ExtractToDirectory(tempZip, targetDir);

                    try { File.Delete(tempZip); } catch { }
                }
            }

            Console.ForegroundColor = ConsoleColor.Green;
            Console.WriteLine("✔ 核心檔案釋放成功！");
            Console.ResetColor();

            // 檢查 Python 環境並執行安裝初始化
            Console.WriteLine("\n[3/3] 正在檢查系統環境並註冊快捷方式...");
            string[] python = FindPython();
            if (python != null)
            {
                var psi = new ProcessStartInfo(python[0], "-m installer")
                {
                    UseShellExecute = false,
                    WorkingDirectory = targetDir,
                };
                psi.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8";
                psi.EnvironmentVariables["PYTHONUTF8"] = "1";
                try
                {
                    using (Process p = Process.Start(psi))
                    {
                        p.WaitForExit();
                    }
                }
                catch (Exception ex)
                {
                    Console.WriteLine("  (註冊啟動項略過: " + ex.Message + ")");
                }
            }
            else
            {
                Console.ForegroundColor = ConsoleColor.Yellow;
                Console.WriteLine("💡 系統未偵測到全域 Python 3.9+。");
                Console.WriteLine("   核心檔案已安全釋放至: " + targetDir);
                Console.WriteLine("   安裝 Python 後即可由目錄內開始使用。");
                Console.ResetColor();
            }

            Console.ForegroundColor = ConsoleColor.Green;
            Console.WriteLine("\n🎉 Syntra Agent 安裝完成！");
            Console.ResetColor();
        }
        catch (Exception ex)
        {
            Console.ForegroundColor = ConsoleColor.Red;
            Console.WriteLine("✘ 安裝過程發生例外：" + ex.Message);
            Console.ResetColor();
        }

        PauseOnExit();
        return 0;
    }

    private static void PauseOnExit()
    {
        Console.WriteLine("\n按任意鍵退出安裝程式...");
        try { Console.ReadKey(); } catch { }
    }

    private static string[] FindPython()
    {
        string custom = Environment.GetEnvironmentVariable("SYNTRA_PYTHON");
        string[][] candidates =
        {
            string.IsNullOrEmpty(custom) ? null : new[] { custom },
            new[] { "python" },
            new[] { "py", "-3" },
            new[] { "python3" },
        };
        foreach (string[] c in candidates)
        {
            if (c == null) continue;
            string prefix = c.Length > 1 ? c[1] + " " : "";
            if (Probe(c[0], prefix + "-c \"import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)\""))
                return c;
        }
        return null;
    }

    private static bool Probe(string file, string arguments)
    {
        try
        {
            var psi = new ProcessStartInfo(file, arguments)
            {
                UseShellExecute = false,
                CreateNoWindow = true,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
            };
            using (Process p = Process.Start(psi))
            {
                p.WaitForExit();
                return p.ExitCode == 0;
            }
        }
        catch { return false; }
    }
}
