// Syntra 星樞 安裝版啟動器（安裝目錄裡的 Syntra.exe）
// 用安裝包內建的 Python 執行環境（runtime\Syntra.exe）開啟桌面版，使用者電腦不需要安裝 Python。
using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Windows.Forms;

[assembly: AssemblyTitle("Syntra 星樞")]
[assembly: AssemblyProduct("Syntra 星樞")]
[assembly: AssemblyDescription("Syntra 星樞 桌面協作平台")]
[assembly: AssemblyVersion("2.5.1.0")]

internal static class SyntraLauncher
{
    [STAThread]
    private static void Main(string[] args)
    {
        string root = AppDomain.CurrentDomain.BaseDirectory.TrimEnd('\\');
        string runtime = Path.Combine(root, "runtime", "Syntra.exe");
        string app = Path.Combine(root, "desktop_app.py");

        if (!File.Exists(runtime) || !File.Exists(app))
        {
            MessageBox.Show("Syntra 的程式檔不完整，請重新執行安裝程式修復。\n\n缺少：" +
                            (File.Exists(runtime) ? app : runtime),
                            "Syntra 星樞", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return;
        }

        string extra = "";
        foreach (string a in args) extra += " \"" + a.Replace("\"", "") + "\"";

        var psi = new ProcessStartInfo(runtime, "\"" + app + "\"" + extra)
        {
            UseShellExecute = false,
            CreateNoWindow = true,
            WorkingDirectory = root
        };
        // 只用內建環境：清掉可能指向使用者自己 Python 的環境變數
        psi.EnvironmentVariables.Remove("PYTHONHOME");
        psi.EnvironmentVariables.Remove("PYTHONPATH");
        psi.EnvironmentVariables.Remove("PYTHONSTARTUP");
        psi.EnvironmentVariables["PYTHONNOUSERSITE"] = "1";
        psi.EnvironmentVariables["PYTHONUTF8"] = "1";
        psi.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8";

        try { Process.Start(psi); }
        catch (Exception ex)
        {
            MessageBox.Show("無法啟動 Syntra：" + ex.Message, "Syntra 星樞", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }
}
