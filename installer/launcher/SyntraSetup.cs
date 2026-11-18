// Syntra 星樞 一鍵安裝啟動器
// 放在專案根目錄（與 installer\ 資料夾同層），雙擊即可啟動安裝程式。
// 它只負責：找到電腦上的 Python → 執行 `python -m installer [參數]`。
// 不含任何安裝邏輯，參數會原封不動轉給 installer（例如 --recommended --dry-run）。
//
// 編譯：powershell -ExecutionPolicy Bypass -File installer\build_exe.ps1
using System;
using System.Diagnostics;
using System.IO;
using System.Text;

[assembly: System.Reflection.AssemblyTitle("Syntra 星樞 安裝程式")]
[assembly: System.Reflection.AssemblyProduct("Syntra")]
[assembly: System.Reflection.AssemblyVersion("1.0.0.0")]

internal static class SyntraSetup
{
    private static int Main(string[] args)
    {
        try { Console.OutputEncoding = Encoding.UTF8; } catch { }
        Console.Title = "Syntra 星樞 安裝程式";
        bool doubleClicked = args.Length == 0;
        int rc = Run(args);
        if (doubleClicked)
        {
            Console.WriteLine();
            Console.Write("按 Enter 關閉視窗...");
            try { Console.ReadLine(); } catch { }
        }
        return rc;
    }

    private static int Run(string[] args)
    {
        string root = AppDomain.CurrentDomain.BaseDirectory.TrimEnd('\\');
        if (!File.Exists(Path.Combine(root, "installer", "__main__.py")))
        {
            Console.WriteLine("✘ 找不到 installer 資料夾。請把這個 .exe 放在 Syntra 專案根目錄再執行。");
            Console.WriteLine("  目前位置：" + root);
            return 2;
        }

        string[] python = FindPython();
        if (python == null)
        {
            Console.WriteLine("✘ 找不到 Python 3.9 以上版本。");
            Console.WriteLine("  請到 https://www.python.org/downloads/ 下載安裝，");
            Console.WriteLine("  安裝時記得勾選「Add python.exe to PATH」，裝好後再雙擊本程式。");
            return 2;
        }

        var sb = new StringBuilder();
        for (int i = 1; i < python.Length; i++) sb.Append(python[i]).Append(' ');
        sb.Append("-m installer");
        foreach (string a in args) sb.Append(' ').Append(Quote(a));

        var psi = new ProcessStartInfo(python[0], sb.ToString())
        {
            UseShellExecute = false,
            WorkingDirectory = root,
        };
        psi.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8";
        psi.EnvironmentVariables["PYTHONUTF8"] = "1";
        try
        {
            using (Process p = Process.Start(psi))
            {
                p.WaitForExit();
                return p.ExitCode;
            }
        }
        catch (Exception ex)
        {
            Console.WriteLine("✘ 無法啟動 Python：" + ex.Message);
            return 2;
        }
    }

    // 依序嘗試：環境變數 SYNTRA_PYTHON → PATH 上的 python（Syntra 平常用的那個）→ py 啟動器 → python3
    // 回傳可用的 [執行檔, 額外參數...]
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

    private static bool Probe(string exe, string arguments)
    {
        try
        {
            var psi = new ProcessStartInfo(exe, arguments)
            {
                UseShellExecute = false,
                CreateNoWindow = true,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
            };
            using (Process p = Process.Start(psi))
            {
                if (!p.WaitForExit(15000)) { try { p.Kill(); } catch { } return false; }
                return p.ExitCode == 0;
            }
        }
        catch
        {
            return false;
        }
    }

    private static string Quote(string a)
    {
        if (a.Length > 0 && a.IndexOfAny(new[] { ' ', '\t', '"' }) < 0) return a;
        return "\"" + a.Replace("\"", "\\\"") + "\"";
    }
}
